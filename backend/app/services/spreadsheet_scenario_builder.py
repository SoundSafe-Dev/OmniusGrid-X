"""
Spreadsheet Scenario Builder

Converts parsed workbook tabs (one DataFrame per tab) into CorrelationScenario
objects for the correlation AI engine.

Modes:
- "window" (default): group rows across all tabs by a shared key
  (date [+ shift] [+ asset_id]) into one scenario per window. Each contributing
  tab supplies an OperationalMetric for its domain, and pairwise CrossDomainLinks
  are created between co-occurring domains keyed on the shared interaction token.
  This yields cross-tab linkage and full coverage (all windows are emitted).
- "tab": one scenario for the whole workbook; active_domains = all mapped tabs,
  each tab contributing an aggregated metric.
- "row": one scenario per row (guarded by a max-row cap).
"""

from typing import Dict, List, Iterator, Optional, Any, Tuple
from datetime import datetime, timezone
import math

from app.models.domain_interaction import (
    DomainType,
    OperationalMetric,
    CrossDomainLink,
    CorrelationScenario,
)
from app.services.spreadsheet_domain_mapper import (
    map_workbook_domains,
    WorkbookDomainMapping,
)


# Candidate column names used to build the window grouping key.
DATE_KEYS = ["date", "time", "timestamp", "posting_date", "order_date"]
SHIFT_KEYS = ["shift"]
ASSET_KEYS = ["asset_id", "asset", "trailer_id", "equipment_id", "machine_id"]
STATUS_KEYS = ["status", "maintenance_status", "incident_severity", "risk_level",
               "stockout_risk", "detention_risk", "priority"]

# Caps to keep memory/compute bounded while preserving full coverage via paging.
DEFAULT_MAX_SCENARIOS = 5000
DEFAULT_MAX_ROW_MODE = 2000


def _severity_from_value(value: Any) -> float:
    """Map a categorical status/severity value to a 0.0-1.0 severity_impact."""
    if value is None:
        return 0.1
    text = str(value).strip().lower()
    critical = {"critical", "high", "severe", "failed", "fail", "down", "emergency"}
    warning = {"warning", "medium", "moderate", "degraded", "watch", "delayed", "blocked"}
    normal = {"normal", "low", "ok", "healthy", "passed", "pass", "good", "active",
              "completed", "complete"}
    if text in critical:
        return 0.85
    if text in warning:
        return 0.5
    if text in normal:
        return 0.15
    return 0.3


def _row_severity(row: Dict[str, Any]) -> float:
    """Derive the strongest severity signal from a row's status-like columns."""
    severities = []
    for key, val in row.items():
        if any(sk in str(key).lower() for sk in STATUS_KEYS):
            severities.append(_severity_from_value(val))
    return max(severities) if severities else 0.2


def _json_safe(value: Any) -> Any:
    """Make a cell value JSON-serializable for payload_snapshot."""
    if value is None:
        return None
    # Handle floats / NaN
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (int, bool, str)):
        return value
    # pandas Timestamp / datetime / numpy types -> str
    try:
        if hasattr(value, "isoformat"):
            return value.isoformat()
    except Exception:
        pass
    # numpy scalar -> python scalar
    try:
        import numpy as np  # local import; available in backend env
        if isinstance(value, np.generic):
            scalar = value.item()
            if isinstance(scalar, float) and (math.isnan(scalar) or math.isinf(scalar)):
                return None
            return scalar
    except Exception:
        pass
    return str(value)


def _row_to_payload(row: Dict[str, Any], max_fields: int = 60) -> Dict[str, Any]:
    """Convert a row mapping into a JSON-safe payload_snapshot dict (capped)."""
    payload: Dict[str, Any] = {}
    for i, (key, val) in enumerate(row.items()):
        if i >= max_fields:
            payload["_truncated_fields"] = True
            break
        payload[str(key)] = _json_safe(val)
    return payload


def _find_key_column(columns: List[str], candidates: List[str]) -> Optional[str]:
    """Return the first column whose normalized name matches a candidate key."""
    lowered = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand in lowered:
            return lowered[cand]
    # substring match
    for col in columns:
        cl = col.lower()
        if any(cand in cl for cand in candidates):
            return col
    return None


def _window_key_for_row(row: Dict[str, Any], date_col: Optional[str],
                        shift_col: Optional[str]) -> Optional[str]:
    """Build a window grouping key (date[+shift]) for a row."""
    if not date_col:
        return None
    date_val = _json_safe(row.get(date_col))
    if date_val is None:
        return None
    # normalize date to YYYY-MM-DD prefix when possible
    date_str = str(date_val)[:10]
    if shift_col and row.get(shift_col) is not None:
        return f"{date_str}|{_json_safe(row.get(shift_col))}"
    return date_str


def _endpoint_for_domain(domain: DomainType, tab_name: str) -> str:
    return f"/intake/{domain.value.lower()}/{tab_name}"


def build_scenarios(
    tabs: Dict[str, "Any"],  # {tab_name: pandas.DataFrame}
    mode: str = "window",
    max_scenarios: int = DEFAULT_MAX_SCENARIOS,
    source_id: str = "intake",
) -> Iterator[CorrelationScenario]:
    """
    Build CorrelationScenario objects from workbook tabs.

    Args:
        tabs: mapping of tab name -> pandas DataFrame
        mode: "window" | "tab" | "row"
        max_scenarios: hard cap on number of scenarios yielded
        source_id: identifier used in scenario_id prefixes

    Yields:
        CorrelationScenario instances (validated by Pydantic on construction).
    """
    # Build {tab: columns} for domain mapping
    tab_columns = {name: list(df.columns) for name, df in tabs.items()}
    mapping = map_workbook_domains(tab_columns)

    if not mapping.tab_domains:
        return  # nothing mappable

    if mode == "tab":
        yield from _build_tab_mode(tabs, mapping, source_id)
    elif mode == "row":
        yield from _build_row_mode(tabs, mapping, source_id, max_scenarios)
    else:
        yield from _build_window_mode(tabs, mapping, source_id, max_scenarios)


def _build_links(domains: List[DomainType], interaction_key: str,
                 severity: float) -> List[CrossDomainLink]:
    """Create pairwise sequential links between co-occurring domains."""
    links: List[CrossDomainLink] = []
    for i in range(len(domains) - 1):
        links.append(CrossDomainLink(
            source_domain=domains[i],
            target_domain=domains[i + 1],
            interaction_key=interaction_key,
            severity_impact=round(min(max(severity, 0.0), 1.0), 2),
            correlation_type="temporal",
        ))
    return links


def _build_window_mode(tabs, mapping: WorkbookDomainMapping, source_id: str,
                       max_scenarios: int) -> Iterator[CorrelationScenario]:
    # Pre-compute key columns per mapped tab
    tab_info: Dict[str, Dict[str, Optional[str]]] = {}
    for tab_name in mapping.tab_domains:
        cols = list(tabs[tab_name].columns)
        tab_info[tab_name] = {
            "date": _find_key_column(cols, DATE_KEYS),
            "shift": _find_key_column(cols, SHIFT_KEYS),
            "asset": _find_key_column(cols, ASSET_KEYS),
        }

    # Collect window -> {tab -> list of row dicts}
    windows: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    window_assets: Dict[str, Optional[str]] = {}

    for tab_name, domain in mapping.tab_domains.items():
        df = tabs[tab_name]
        info = tab_info[tab_name]
        date_col = info["date"]
        shift_col = info["shift"]
        asset_col = info["asset"]
        if not date_col:
            # No temporal key -> represent the whole tab as a single synthetic window
            key = f"tab::{tab_name}"
            windows.setdefault(key, {}).setdefault(tab_name, [])
            for record in df.head(50).to_dict(orient="records"):
                windows[key][tab_name].append(record)
            continue
        for record in df.to_dict(orient="records"):
            wkey = _window_key_for_row(record, date_col, shift_col)
            if wkey is None:
                continue
            windows.setdefault(wkey, {}).setdefault(tab_name, []).append(record)
            if asset_col and window_assets.get(wkey) is None:
                window_assets[wkey] = _json_safe(record.get(asset_col))

    count = 0
    for wkey, tab_rows in windows.items():
        if count >= max_scenarios:
            break
        # Only build cross-tab scenarios where >=2 domains present, but still
        # emit single-domain windows for full coverage.
        domains: List[DomainType] = []
        metrics: List[OperationalMetric] = []
        max_sev = 0.2
        for tab_name, rows in tab_rows.items():
            domain = mapping.tab_domains[tab_name]
            if domain not in domains:
                domains.append(domain)
            # Aggregate: first row as representative + count
            representative = rows[0] if rows else {}
            sev = max((_row_severity(r) for r in rows), default=0.2)
            max_sev = max(max_sev, sev)
            payload = _row_to_payload(representative)
            payload["_row_count"] = len(rows)
            payload["_window"] = wkey
            metrics.append(OperationalMetric(
                endpoint=_endpoint_for_domain(domain, tab_name),
                payload_snapshot=payload,
                timestamp=str(wkey).split("|")[0],
            ))
        interaction_key = window_assets.get(wkey) or wkey
        links = _build_links(domains, str(interaction_key), max_sev)
        scenario = CorrelationScenario(
            scenario_id=f"{source_id}-win-{count:06d}",
            active_domains=domains,
            domain_links=links,
            ingested_metrics=metrics,
        )
        count += 1
        yield scenario


def _build_tab_mode(tabs, mapping: WorkbookDomainMapping,
                    source_id: str) -> Iterator[CorrelationScenario]:
    domains: List[DomainType] = []
    metrics: List[OperationalMetric] = []
    max_sev = 0.2
    for tab_name, domain in mapping.tab_domains.items():
        df = tabs[tab_name]
        if domain not in domains:
            domains.append(domain)
        records = df.to_dict(orient="records")
        sev = max((_row_severity(r) for r in records[:200]), default=0.2)
        max_sev = max(max_sev, sev)
        representative = records[0] if records else {}
        payload = _row_to_payload(representative)
        payload["_row_count"] = len(records)
        metrics.append(OperationalMetric(
            endpoint=_endpoint_for_domain(domain, tab_name),
            payload_snapshot=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))
    links = _build_links(domains, source_id, max_sev)
    yield CorrelationScenario(
        scenario_id=f"{source_id}-tab-000000",
        active_domains=domains,
        domain_links=links,
        ingested_metrics=metrics,
    )


def _build_row_mode(tabs, mapping: WorkbookDomainMapping, source_id: str,
                    max_scenarios: int) -> Iterator[CorrelationScenario]:
    cap = min(max_scenarios, DEFAULT_MAX_ROW_MODE)
    count = 0
    for tab_name, domain in mapping.tab_domains.items():
        df = tabs[tab_name]
        for record in df.to_dict(orient="records"):
            if count >= cap:
                return
            sev = _row_severity(record)
            metric = OperationalMetric(
                endpoint=_endpoint_for_domain(domain, tab_name),
                payload_snapshot=_row_to_payload(record),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            yield CorrelationScenario(
                scenario_id=f"{source_id}-row-{count:06d}",
                active_domains=[domain],
                domain_links=[],
                ingested_metrics=[metric],
            )
            count += 1
