"""
NLP Correlation AI API Endpoints

API endpoints for natural language interaction with the correlation AI engine,
and Intake Inbox for data upload and analysis.
"""

import json
from typing import List, Dict, Any, Optional, Set
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import math
import structlog

# `get_tenant_db` binds `app.current_org_id` on the session; `intake_items` is under
# FORCE ROW LEVEL SECURITY (migration 033), so the unscoped session read zero rows
# and refused every write here (FS-431).
from app.middleware.tenant_isolation import get_tenant_db
from app.api.auth import get_current_active_user
from app.db.models import User
from app.db.models import IntakeItem as IntakeItemModel
from app.services.correlation_ai_engine import correlation_ai_engine
from app.services.correlation_registry_integration import correlation_registry_integration
from sqlalchemy import select, func

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/nlp/correlation", tags=["NLP Correlation"])


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe Python values."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _round_metric(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return round(numeric, 3)


def _find_column(columns: List[str], keywords: List[str]) -> Optional[str]:
    lower_lookup = {str(column).lower(): column for column in columns}
    for keyword in keywords:
        for lower_name, original_name in lower_lookup.items():
            if keyword in lower_name:
                return original_name
    return None


_METRIC_NAME_EXCLUDES = (
    "type", "category", "code", "description", "reason", "status", "mode",
    "class", "label", "comment", "text", "note", "name",
)

_DEFECT_QUANTITY_KEYWORDS = [
    "defect_count", "defects_count", "num_defects", "defect_qty", "defects", "defect",
]


def _find_metric_column(columns: List[str], keywords: List[str]) -> Optional[str]:
    """Match a column by keyword but skip categorical fields (e.g. defect_type)."""
    lower_lookup = {str(column).lower(): column for column in columns}
    for keyword in keywords:
        for lower_name, original_name in lower_lookup.items():
            if keyword not in lower_name:
                continue
            if any(excluded in lower_name for excluded in _METRIC_NAME_EXCLUDES):
                continue
            return original_name
    return None


_GROUPING_COLUMN_EXCLUDES = (
    "payment", "invoice", "paid", "billing", "order_status", "po_status",
    "transaction", "receipt", "payable", "receivable", "settlement",
)

_INVALID_GROUP_VALUES = {
    "paid", "unpaid", "pending", "complete", "completed", "open", "closed",
    "yes", "no", "n/a", "na", "unknown", "none", "null", "active", "inactive",
}


def _find_grouping_column(columns: List[str], keywords: List[str]) -> Optional[str]:
    """Operational grouping columns only — skip payment/status/finance noise."""
    lower_lookup = {str(column).lower(): column for column in columns}
    for keyword in keywords:
        for lower_name, original_name in lower_lookup.items():
            if keyword not in lower_name:
                continue
            if any(excluded in lower_name for excluded in _GROUPING_COLUMN_EXCLUDES):
                continue
            if lower_name in {"status", "state"}:
                continue
            return original_name
    return None


def _is_valid_operational_group_value(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text or text in _INVALID_GROUP_VALUES:
        return False
    if len(text) <= 2 and text.isalpha():
        return False
    return True


def _find_defect_quantity_column(columns: List[str]) -> Optional[str]:
    return _find_metric_column(columns, _DEFECT_QUANTITY_KEYWORDS)


def _find_issue_group_column(columns: List[str]) -> Optional[str]:
    return _find_grouping_column(
        columns,
        ["delay_reason", "delay_code", "issue_type", "failure_mode", "root_cause", "delay"],
    )


def _coerce_numeric_series(df: Any, column: Optional[str]) -> Any:
    if not column or column not in df.columns:
        return None
    import pandas as pd

    series = pd.to_numeric(df[column], errors="coerce")
    if series.notna().sum() == 0:
        return None
    return series


def _safe_numeric_sum(df: Any, column: Optional[str]) -> Optional[float]:
    series = _coerce_numeric_series(df, column)
    if series is None:
        return None
    return _round_metric(series.sum())


def _safe_numeric_mean(df: Any, column: Optional[str]) -> Optional[float]:
    series = _coerce_numeric_series(df, column)
    if series is None:
        return None
    return _round_metric(series.mean())


def _safe_numeric_min(df: Any, column: Optional[str]) -> Optional[float]:
    series = _coerce_numeric_series(df, column)
    if series is None:
        return None
    return _round_metric(series.min())


def _safe_numeric_max(df: Any, column: Optional[str]) -> Optional[float]:
    series = _coerce_numeric_series(df, column)
    if series is None:
        return None
    return _round_metric(series.max())


def _safe_numeric_first_last(df: Any, column: Optional[str]) -> tuple:
    series = _coerce_numeric_series(df, column)
    if series is None:
        return None, None
    cleaned = series.dropna()
    if cleaned.empty:
        return None, None
    first_value = cleaned.iloc[0]
    last_value = cleaned.iloc[-1]
    return _round_metric(first_value), _round_metric(last_value)


def _numeric_describe(df: Any) -> Dict[str, Any]:
    if df.empty:
        return {}
    import pandas as pd

    numeric_df = df.select_dtypes(include="number")
    if numeric_df.empty:
        coerced_frames = []
        for column in df.columns[:40]:
            series = pd.to_numeric(df[column], errors="coerce")
            if series.notna().sum() > 0:
                coerced_frames.append(series.rename(column))
        if coerced_frames:
            numeric_df = pd.concat(coerced_frames, axis=1)
    if numeric_df.empty:
        return {}
    return _json_safe(numeric_df.describe().to_dict())


def _build_linking_metadata(df: Any) -> Dict[str, Any]:
    """Distinct assets/lines and date range for cross-file correlation (full column scan)."""
    if df.empty:
        return {"row_count": 0, "date_range": None, "year_labels": [], "distinct_assets": [], "distinct_lines": []}

    import pandas as pd

    columns = [str(c) for c in df.columns]
    date_col = _find_column(columns, ["date", "time", "timestamp", "posting_date", "order_date"])
    asset_col = _find_column(columns, ["asset_id", "asset", "equipment_id", "machine_id"])
    line_col = _find_column(columns, ["production_line", "line"])

    metadata: Dict[str, Any] = {"row_count": int(len(df)), "date_range": None, "year_labels": [], "distinct_assets": [], "distinct_lines": []}

    if date_col:
        dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if not dates.empty:
            metadata["date_range"] = {
                "min": str(dates.min().date()),
                "max": str(dates.max().date()),
            }
            metadata["year_labels"] = sorted({int(y) for y in dates.dt.year.dropna().unique()})

    if asset_col:
        metadata["distinct_assets"] = (
            df[asset_col].dropna().astype(str).str.strip().unique().tolist()[:500]
        )
    if line_col:
        metadata["distinct_lines"] = (
            df[line_col].dropna().astype(str).str.strip().unique().tolist()[:100]
        )

    return metadata


def _merge_workbook_linking(tab_metas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge per-tab linking metadata into workbook-level linking_metadata."""
    if not tab_metas:
        return {"row_count": 0, "date_range": None, "year_labels": [], "distinct_assets": [], "distinct_lines": []}

    assets: List[str] = []
    lines: List[str] = []
    years: Set[int] = set()
    ranges = []
    rows = 0
    for m in tab_metas:
        rows += int(m.get("row_count") or 0)
        assets.extend(m.get("distinct_assets") or [])
        lines.extend(m.get("distinct_lines") or [])
        years.update(m.get("year_labels") or [])
        if m.get("date_range"):
            ranges.append(m["date_range"])

    merged_range = None
    if ranges:
        merged_range = {
            "min": min(r["min"] for r in ranges),
            "max": max(r["max"] for r in ranges),
        }

    return {
        "row_count": rows,
        "date_range": merged_range,
        "year_labels": sorted(years),
        "distinct_assets": list(dict.fromkeys(assets))[:500],
        "distinct_lines": list(dict.fromkeys(lines))[:100],
    }


def _records_for_model(df: Any, limit: int = 5) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    return _json_safe(df.head(limit).where(df.notna(), None).to_dict(orient="records"))


def _numeric_profile(df: Any) -> Dict[str, Any]:
    profile: Dict[str, Any] = {}
    numeric_df = df.select_dtypes(include="number")
    for column in numeric_df.columns[:25]:
        series = numeric_df[column].dropna()
        if series.empty:
            continue

        first_value = series.iloc[0]
        last_value = series.iloc[-1]
        delta = last_value - first_value
        percent_change = None
        if first_value != 0:
            percent_change = (delta / abs(first_value)) * 100

        profile[str(column)] = {
            "count": int(series.count()),
            "min": _round_metric(series.min()),
            "max": _round_metric(series.max()),
            "mean": _round_metric(series.mean()),
            "median": _round_metric(series.median()),
            "sum": _round_metric(series.sum()),
            "first": _round_metric(first_value),
            "last": _round_metric(last_value),
            "first_to_last_delta": _round_metric(delta),
            "first_to_last_percent_change": _round_metric(percent_change),
        }
    return profile


def _categorical_profile(df: Any) -> Dict[str, Any]:
    profile: Dict[str, Any] = {}
    for column in df.columns[:30]:
        series = df[column].dropna()
        if series.empty:
            continue
        unique_count = int(series.nunique())
        if unique_count > 25 and not df[column].dtype == "object":
            continue
        counts = series.astype(str).value_counts().head(8)
        profile[str(column)] = {
            "unique_count": unique_count,
            "top_values": _json_safe(counts.to_dict()),
        }
    return profile


def _operational_profile(df: Any) -> Dict[str, Any]:
    columns = [str(column) for column in df.columns]
    planned_col = _find_column(columns, ["planned_units", "planned", "target"])
    actual_col = _find_column(columns, ["actual_units", "actual", "produced"])
    downtime_col = _find_metric_column(columns, ["downtime"])
    defect_col = _find_defect_quantity_column(columns)
    vibration_col = _find_metric_column(columns, ["vibration"])
    loss_col = _find_metric_column(columns, ["estimated_loss", "loss", "cost"])
    delay_col = _find_column(columns, ["delay_reason", "delay"])
    maintenance_col = _find_column(columns, ["maintenance"])
    priority_col = _find_column(columns, ["priority"])

    metrics: Dict[str, Any] = {}
    working_df = df.copy()

    if planned_col and actual_col:
        planned = _coerce_numeric_series(working_df, planned_col)
        actual = _coerce_numeric_series(working_df, actual_col)
        if planned is not None and actual is not None:
            working_df["_actual_gap"] = planned - actual
            working_df["_attainment_pct"] = (actual / planned.replace(0, math.nan)) * 100
            metrics["planned_vs_actual"] = {
                "planned_total": _round_metric(planned.sum()),
                "actual_total": _round_metric(actual.sum()),
                "shortfall_total": _round_metric((planned - actual).sum()),
                "average_attainment_pct": _round_metric(working_df["_attainment_pct"].mean()),
                "worst_shortfall": _round_metric(working_df["_actual_gap"].max()),
            }

    for source_col, label in [
        (downtime_col, "downtime"),
        (defect_col, "defects"),
        (vibration_col, "vibration"),
        (loss_col, "estimated_loss"),
    ]:
        if not source_col:
            continue
        series = _coerce_numeric_series(working_df, source_col)
        if series is None:
            continue
        first_value, last_value = _safe_numeric_first_last(working_df, source_col)
        metrics[label] = {
            "total": _round_metric(series.sum()),
            "average": _round_metric(series.mean()),
            "min": _round_metric(series.min()),
            "max": _round_metric(series.max()),
            "first": first_value,
            "last": last_value,
            "first_to_last_delta": _round_metric(last_value - first_value) if first_value is not None and last_value is not None else None,
        }

    for source_col, label in [
        (delay_col, "delay_reason_counts"),
        (maintenance_col, "maintenance_status_counts"),
        (priority_col, "priority_counts"),
    ]:
        if source_col:
            metrics[label] = _json_safe(
                working_df[source_col].dropna().astype(str).value_counts().head(8).to_dict()
            )

    return metrics


def _row_context_columns(df: Any) -> List[str]:
    keywords = [
        "date", "shift", "facility", "production_line", "line", "asset_id", "asset_name",
        "planned", "actual", "downtime", "defect", "temperature", "vibration",
        "maintenance", "delay", "priority", "estimated_loss", "loss",
    ]
    selected = [
        column for column in df.columns
        if any(keyword in str(column).lower() for keyword in keywords)
    ]
    return selected[:16] or list(df.columns[:12])


def _top_rows_by_signal(df: Any) -> Dict[str, List[Dict[str, Any]]]:
    top_rows: Dict[str, List[Dict[str, Any]]] = {}
    columns = [str(column) for column in df.columns]
    context_columns = _row_context_columns(df)
    signals = {
        "highest_downtime_rows": _find_metric_column(columns, ["downtime"]),
        "highest_defect_rows": _find_defect_quantity_column(columns),
        "highest_vibration_rows": _find_metric_column(columns, ["vibration"]),
        "highest_loss_rows": _find_metric_column(columns, ["estimated_loss", "loss", "cost"]),
    }

    planned_col = _find_column(columns, ["planned_units", "planned", "target"])
    actual_col = _find_column(columns, ["actual_units", "actual", "produced"])
    working_df = df.copy()
    if planned_col and actual_col:
        planned = _coerce_numeric_series(working_df, planned_col)
        actual = _coerce_numeric_series(working_df, actual_col)
        if planned is not None and actual is not None:
            working_df["_actual_gap"] = planned - actual
            signals["largest_actual_vs_planned_shortfall_rows"] = "_actual_gap"

    for label, column in signals.items():
        if not column or column not in working_df.columns:
            continue
        sort_column = column
        if not column.startswith("_"):
            coerced = _coerce_numeric_series(working_df, column)
            if coerced is None:
                continue
            sort_column = f"_sort_{column}"
            working_df = working_df.copy()
            working_df[sort_column] = coerced
        ranked = working_df.sort_values(sort_column, ascending=False).head(5).copy()
        display_columns = context_columns.copy()
        if column.startswith("_"):
            display_columns.append(column)
        top_rows[label] = _records_for_model(ranked[display_columns], limit=5)

    return top_rows


def _group_profile(df: Any) -> Dict[str, Any]:
    columns = [str(column) for column in df.columns]
    group_columns = [
        _find_column(columns, ["production_line", "line"]),
        _find_column(columns, ["asset_id", "asset"]),
        _find_column(columns, ["facility"]),
        _find_column(columns, ["shift"]),
    ]
    group_columns = [column for column in group_columns if column]

    downtime_col = _find_metric_column(columns, ["downtime"])
    defect_col = _find_defect_quantity_column(columns)
    vibration_col = _find_metric_column(columns, ["vibration"])
    loss_col = _find_metric_column(columns, ["estimated_loss", "loss", "cost"])
    planned_col = _find_column(columns, ["planned_units", "planned", "target"])
    actual_col = _find_column(columns, ["actual_units", "actual", "produced"])

    working_df = df.copy()
    if planned_col and actual_col:
        planned = _coerce_numeric_series(working_df, planned_col)
        actual = _coerce_numeric_series(working_df, actual_col)
        if planned is not None and actual is not None:
            working_df["_actual_gap"] = planned - actual
            working_df["_attainment_pct"] = (actual / planned.replace(0, math.nan)) * 100

    value_columns = [
        (downtime_col, "downtime_total", "sum"),
        (defect_col, "defect_total", "sum"),
        (vibration_col, "vibration_avg", "mean"),
        (loss_col, "estimated_loss_total", "sum"),
        ("_actual_gap", "actual_shortfall_total", "sum"),
        ("_attainment_pct", "attainment_pct_avg", "mean"),
    ]

    profile: Dict[str, Any] = {}
    for group_col in group_columns:
        rows = []
        for value, group in working_df.groupby(group_col, dropna=True):
            row: Dict[str, Any] = {"value": _json_safe(value), "rows": int(len(group))}
            for source_col, label, agg in value_columns:
                if not source_col or source_col not in group.columns:
                    continue
                series = _coerce_numeric_series(group, source_col)
                if series is None:
                    continue
                metric_value = series.sum() if agg == "sum" else series.mean()
                row[label] = _round_metric(metric_value)
            rows.append(row)

        if rows:
            rows.sort(
                key=lambda item: (
                    item.get("downtime_total") or 0,
                    item.get("defect_total") or 0,
                    item.get("estimated_loss_total") or 0,
                    item.get("actual_shortfall_total") or 0,
                ),
                reverse=True,
            )
            profile[str(group_col)] = rows[:8]

    return profile


def _build_spreadsheet_profile(df: Any) -> Dict[str, Any]:
    return {
        "numeric_summary": _numeric_profile(df),
        "categorical_summary": _categorical_profile(df),
        "operational_summary": _operational_profile(df),
        "group_summary": _group_profile(df),
        "highest_risk_rows": _top_rows_by_signal(df),
        "first_rows": _records_for_model(df, limit=5),
        "last_rows": _records_for_model(df.tail(5), limit=5),
    }


def _build_numeric_comparison_findings(df: Any) -> List[str]:
    if df.empty:
        return []

    columns = [str(column) for column in df.columns]
    planned_col = _find_column(columns, ["planned_units", "planned", "target"])
    actual_col = _find_column(columns, ["actual_units", "actual", "produced"])
    defect_col = _find_defect_quantity_column(columns)
    downtime_col = _find_metric_column(columns, ["downtime_minutes", "downtime"])
    loss_col = _find_metric_column(columns, ["estimated_cost", "estimated_loss", "loss", "cost"])
    vibration_col = _find_metric_column(columns, ["vibration_level", "vibration"])
    asset_col = _find_column(columns, ["asset_id", "asset"])
    line_col = _find_column(columns, ["production_line", "line"])
    shift_col = _find_column(columns, ["shift"])

    findings: List[str] = []

    if defect_col and planned_col:
        defect_series = _coerce_numeric_series(df, defect_col)
        planned_series = _coerce_numeric_series(df, planned_col)
        if defect_series is not None and planned_series is not None:
            total_defects = defect_series.sum()
            total_planned = planned_series.sum()
            defects_per_1000_planned = (total_defects / total_planned * 1000) if total_planned else None
            working_df = df.copy()
            working_df["_defects_per_1000_planned"] = (
                defect_series / planned_series.replace(0, math.nan) * 1000
            )
            worst_row = working_df.sort_values("_defects_per_1000_planned", ascending=False).head(1)

            findings.append(
                "Numeric comparison: defect_count vs planned_units | "
                f"total_defect_count={_format_finding_value(total_defects)} | "
                f"total_planned_units={_format_finding_value(total_planned)} | "
                f"defects_per_1000_planned_units={_format_finding_value(_round_metric(defects_per_1000_planned))} | "
                f"worst_row={_row_label(_records_for_model(worst_row, limit=1)[0])}."
            )

            for group_col in [line_col, asset_col, shift_col]:
                if not group_col:
                    continue
                rows = []
                for group_value, group in working_df.groupby(group_col, dropna=True):
                    planned_sum = _safe_numeric_sum(group, planned_col)
                    defect_sum = _safe_numeric_sum(group, defect_col)
                    rows.append({
                        "group": group_value,
                        "planned_units": planned_sum,
                        "defect_count": defect_sum,
                        "defects_per_1000_planned_units": _round_metric(
                            defect_sum / planned_sum * 1000 if planned_sum else None
                        ),
                    })
                rows.sort(key=lambda row: row.get("defects_per_1000_planned_units") or 0, reverse=True)
                top_groups = "; ".join(
                    f"{group_col}={row['group']} defect_count={_format_finding_value(row['defect_count'])} "
                    f"planned_units={_format_finding_value(row['planned_units'])} "
                    f"defects_per_1000={_format_finding_value(row['defects_per_1000_planned_units'])}"
                    for row in rows[:3]
                )
                findings.append(f"Numeric comparison by {group_col}: defect_count vs planned_units | {top_groups}.")

    if actual_col and planned_col:
        actual_total = _safe_numeric_sum(df, actual_col)
        planned_total = _safe_numeric_sum(df, planned_col)
        if actual_total is not None and planned_total is not None:
            shortfall_total = planned_total - actual_total
            attainment = (actual_total / planned_total * 100) if planned_total else None
            findings.append(
                "Numeric comparison: actual_units vs planned_units | "
                f"total_actual_units={_format_finding_value(actual_total)} | "
                f"total_planned_units={_format_finding_value(planned_total)} | "
                f"shortfall_units={_format_finding_value(shortfall_total)} | "
                f"attainment_pct={_format_finding_value(_round_metric(attainment))}."
            )

    if loss_col and downtime_col:
        loss_total = _safe_numeric_sum(df, loss_col)
        downtime_total = _safe_numeric_sum(df, downtime_col)
        if loss_total is not None and downtime_total is not None:
            loss_per_downtime_minute = loss_total / downtime_total if downtime_total else None
            findings.append(
                "Numeric comparison: estimated cost impact vs downtime | "
                f"total_estimated_cost={_format_finding_value(loss_total)} | "
                f"total_downtime={_format_finding_value(downtime_total)} | "
                f"cost_per_downtime_minute={_format_finding_value(_round_metric(loss_per_downtime_minute))}."
            )

    if vibration_col and defect_col:
        vibration_series = _coerce_numeric_series(df, vibration_col)
        defect_series = _coerce_numeric_series(df, defect_col)
        if vibration_series is not None and defect_series is not None:
            working_df = df.copy()
            working_df["_vibration"] = vibration_series
            working_df["_defect_metric"] = defect_series
            high_vibration_threshold = working_df["_vibration"].quantile(0.75)
            high_vibration = working_df[working_df["_vibration"] >= high_vibration_threshold]
            low_vibration = working_df[working_df["_vibration"] < high_vibration_threshold]
            findings.append(
                "Numeric comparison: vibration vs defects | "
                f"high_vibration_threshold={_format_finding_value(_round_metric(high_vibration_threshold))} | "
                f"avg_defects_high_vibration={_format_finding_value(_round_metric(high_vibration['_defect_metric'].mean()))} | "
                f"avg_defects_lower_vibration={_format_finding_value(_round_metric(low_vibration['_defect_metric'].mean()))}."
            )

    return findings[:8]


def _format_finding_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.1f}" if value % 1 else f"{value:,.0f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _top_group_label(profile: Dict[str, Any], group_name: str, metric_name: str) -> Optional[str]:
    groups = profile.get("group_summary", {}).get(group_name) or []
    if not groups:
        return None
    top_group = groups[0]
    value = top_group.get("value")
    metric = top_group.get(metric_name)
    if value is None or metric is None:
        return None
    return f"{group_name}={value} ({metric_name}={_format_finding_value(metric)})"


def _row_label(row: Dict[str, Any]) -> str:
    preferred = [
        "date", "shift", "facility", "production_line", "asset_id", "asset_name",
        "planned_units", "actual_units", "downtime", "downtime_minutes",
        "defect_count", "vibration", "maintenance_status", "delay_reason",
        "priority", "estimated_loss",
    ]
    parts = []
    for key in preferred:
        if key in row and row[key] is not None:
            parts.append(f"{key}={_format_finding_value(row[key])}")
    if parts:
        return "; ".join(parts)
    return "; ".join(f"{key}={_format_finding_value(value)}" for key, value in list(row.items())[:10])


def _column_value(row: Dict[str, Any], column: Optional[str]) -> Any:
    if not column:
        return None
    return row.get(column)


def _owner_for_issue(issue_text: str, columns: List[str]) -> str:
    normalized = issue_text.lower()
    column_text = " ".join(columns).lower()
    if any(term in normalized for term in ("quality", "defect", "hold")):
        return "Quality + Production"
    if any(term in normalized for term in ("maintenance", "sensor", "vibration", "inspection", "equipment")):
        return "Maintenance + Operations"
    if any(term in normalized for term in ("material", "supplier", "inventory", "shortage")):
        return "Supply Planning + Operations"
    if any(term in normalized for term in ("changeover", "setup")):
        return "Production Supervisor"
    if "carrier" in column_text or "shipment" in column_text or "dock" in column_text:
        return "Logistics Operations"
    return "Operations Lead"


def _metric_watch_list(columns: List[str]) -> List[str]:
    candidates = [
        "estimated_loss",
        "estimated_cost_impact_usd",
        "downtime",
        "downtime_minutes",
        "defect_count",
        "actual_units",
        "planned_units",
        "vibration",
        "vibration_level",
        "maintenance_status",
        "delay_reason",
        "priority",
    ]
    lower_lookup = {str(column).lower(): str(column) for column in columns}
    watched = []
    for candidate in candidates:
        for lower_name, original in lower_lookup.items():
            if candidate in lower_name and original not in watched:
                watched.append(original)
    return watched[:5]


def _build_action_plan_for_group(
    group_label: str,
    group_value: Any,
    group: Any,
    columns: List[str],
    rank_col: Optional[str],
) -> Optional[Dict[str, Any]]:
    if group.empty:
        return None

    working_group = group.copy()
    if rank_col and rank_col in working_group.columns:
        sort_col = rank_col
        if not rank_col.startswith("_"):
            coerced = _coerce_numeric_series(working_group, rank_col)
            if coerced is not None:
                sort_col = f"_rank_{rank_col}"
                working_group[sort_col] = coerced
            else:
                sort_col = None
        if sort_col:
            worst_row_df = working_group.sort_values(sort_col, ascending=False).head(1)
        else:
            worst_row_df = working_group.head(1)
    else:
        worst_row_df = working_group.head(1)
    worst_row = _records_for_model(worst_row_df, limit=1)[0]

    loss_col = _find_metric_column(columns, ["estimated_cost", "estimated_loss", "loss", "cost"])
    downtime_col = _find_metric_column(columns, ["downtime"])
    defect_col = _find_defect_quantity_column(columns)
    vibration_col = _find_metric_column(columns, ["vibration"])
    maintenance_col = _find_column(columns, ["maintenance"])
    asset_col = _find_column(columns, ["asset_id", "asset"])
    asset_name_col = _find_column(columns, ["asset_name"])
    line_col = _find_column(columns, ["production_line", "line"])
    shift_col = _find_column(columns, ["shift"])
    priority_col = _find_column(columns, ["priority"])

    issue_text = f"{group_label} {group_value}"
    owner = _owner_for_issue(issue_text, columns)

    facts = {
        "rows": int(len(group)),
        "total_estimated_cost": _safe_numeric_sum(group, loss_col),
        "total_downtime": _safe_numeric_sum(group, downtime_col),
        "total_defects": _safe_numeric_sum(group, defect_col),
        "average_vibration": _safe_numeric_mean(group, vibration_col),
    }

    check_fields = {
        "asset_id": _column_value(worst_row, asset_col),
        "asset_name": _column_value(worst_row, asset_name_col),
        "production_line": _column_value(worst_row, line_col),
        "shift": _column_value(worst_row, shift_col),
        "maintenance_status": _column_value(worst_row, maintenance_col),
        "priority": _column_value(worst_row, priority_col),
        "estimated_cost": _column_value(worst_row, loss_col),
        "downtime": _column_value(worst_row, downtime_col),
        "defect_count": _column_value(worst_row, defect_col),
        "vibration": _column_value(worst_row, vibration_col),
    }
    check_fields = {key: value for key, value in check_fields.items() if value is not None}

    if owner.startswith("Quality"):
        first_action = (
            "Start with the highest-cost row for this issue, contain the affected output, "
            "and compare defect_count by asset, line, and shift before broad process changes."
        )
    elif owner.startswith("Maintenance"):
        first_action = (
            "Inspect the named asset/line first, using downtime, maintenance_status, and vibration "
            "to decide whether this is equipment wear, sensor reliability, or scheduling delay."
        )
    elif owner.startswith("Supply"):
        first_action = (
            "Check the affected line and shift against material availability, then isolate whether "
            "the loss is from shortage timing or downstream downtime."
        )
    elif owner.startswith("Production"):
        first_action = (
            "Review the exact changeover/setup rows by line and shift, then standardize the step "
            "that created the largest cost or downtime outlier."
        )
    else:
        first_action = (
            "Use the worst row as the starting point, assign one owner, and validate the highest "
            "cost, downtime, and quality signals before scaling the fix."
        )

    metrics_to_watch = _metric_watch_list(columns)

    return {
        "issue": f"{group_label}={group_value}",
        "why_it_matters": facts,
        "check_first": check_fields,
        "owner": owner,
        "first_next_shift_action": first_action,
        "metric_to_watch": metrics_to_watch,
        "worst_row": worst_row,
    }


def _build_concrete_action_plan(df: Any) -> List[Dict[str, Any]]:
    if df.empty:
        return []

    columns = [str(column) for column in df.columns]
    loss_col = _find_metric_column(columns, ["estimated_cost", "estimated_loss", "loss", "cost"])
    downtime_col = _find_metric_column(columns, ["downtime"])
    defect_col = _find_defect_quantity_column(columns)
    vibration_col = _find_metric_column(columns, ["vibration"])
    delay_col = _find_issue_group_column(columns)
    maintenance_col = _find_grouping_column(columns, ["maintenance_status", "maintenance"])
    priority_col = _find_grouping_column(columns, ["priority", "severity"])
    asset_col = _find_column(columns, ["asset_id", "asset"])
    line_col = _find_column(columns, ["production_line", "line"])
    shift_col = _find_column(columns, ["shift"])

    rank_col = loss_col or downtime_col or defect_col or vibration_col
    action_items: List[Dict[str, Any]] = []

    primary_group_col = (
        delay_col
        or maintenance_col
        or priority_col
        or asset_col
        or line_col
        or shift_col
    )
    if primary_group_col:
        for group_value, group in df.groupby(primary_group_col, dropna=True):
            if not _is_valid_operational_group_value(group_value):
                continue
            action = _build_action_plan_for_group(
                primary_group_col,
                group_value,
                group,
                columns,
                rank_col,
            )
            if action:
                action_items.append(action)

    def action_sort_key(action: Dict[str, Any]) -> tuple:
        facts = action.get("why_it_matters") or {}
        return (
            facts.get("total_estimated_cost") or 0,
            facts.get("total_downtime") or 0,
            facts.get("total_defects") or 0,
            facts.get("average_vibration") or 0,
        )

    action_items.sort(key=action_sort_key, reverse=True)
    return action_items[:6]


def _format_action_plan_findings(action_plan: List[Dict[str, Any]]) -> List[str]:
    findings = []
    for item in action_plan[:6]:
        facts = item.get("why_it_matters") or {}
        check_first = item.get("check_first") or {}
        check_text = ", ".join(
            f"{key}={_format_finding_value(value)}" for key, value in check_first.items()
        )
        metrics = ", ".join(item.get("metric_to_watch") or [])
        findings.append(
            f"Concrete action plan: issue={item.get('issue')} | owner={item.get('owner')} | "
            f"rows={facts.get('rows')} | total_estimated_cost={_format_finding_value(facts.get('total_estimated_cost'))} | "
            f"total_downtime={_format_finding_value(facts.get('total_downtime'))} | "
            f"total_defects={_format_finding_value(facts.get('total_defects'))} | "
            f"check_first={check_text} | first_next_shift_action={item.get('first_next_shift_action')} | "
            f"metric_to_watch={metrics}."
        )
    return findings


def _build_cost_delay_findings(df: Any) -> List[str]:
    """Deterministic cost-vs-delay facts for spreadsheet chat grounding."""
    columns = [str(column) for column in df.columns]
    delay_col = _find_column(columns, ["delay_reason", "delay"])
    loss_col = _find_metric_column(columns, ["estimated_loss", "loss", "cost"])
    downtime_col = _find_metric_column(columns, ["downtime"])
    defect_col = _find_defect_quantity_column(columns)
    asset_col = _find_column(columns, ["asset_id", "asset"])
    line_col = _find_column(columns, ["production_line", "line"])
    shift_col = _find_column(columns, ["shift"])
    maintenance_col = _find_column(columns, ["maintenance"])

    if not delay_col or not loss_col:
        return []

    working_df = df.copy()
    working_df[delay_col] = working_df[delay_col].fillna("Unknown").astype(str)
    grouped = working_df.groupby(delay_col, dropna=False)
    findings: List[str] = []

    delay_totals = []
    for delay_reason, group in grouped:
        row = {
            "delay_reason": delay_reason,
            "rows": int(len(group)),
            "estimated_loss_total": _safe_numeric_sum(group, loss_col),
        }
        if downtime_col:
            row["downtime_total"] = _safe_numeric_sum(group, downtime_col)
            row["downtime_avg"] = _safe_numeric_mean(group, downtime_col)
        if defect_col:
            row["defect_total"] = _safe_numeric_sum(group, defect_col)
            row["defect_avg"] = _safe_numeric_mean(group, defect_col)
        delay_totals.append(row)

    delay_totals.sort(
        key=lambda item: (
            item.get("estimated_loss_total") or 0,
            item.get("downtime_total") or 0,
            item.get("defect_total") or 0,
        ),
        reverse=True,
    )

    findings.append(
        "Cost-delay correlation: group results by delay_reason using estimated_loss, downtime, and defect_count."
    )
    for item in delay_totals[:6]:
        parts = [
            f"delay_reason={item['delay_reason']}",
            f"rows={item['rows']}",
            f"estimated_loss_total={_format_finding_value(item.get('estimated_loss_total'))}",
        ]
        if item.get("downtime_total") is not None:
            parts.append(f"downtime_total={_format_finding_value(item.get('downtime_total'))}")
            parts.append(f"downtime_avg={_format_finding_value(item.get('downtime_avg'))}")
        if item.get("defect_total") is not None:
            parts.append(f"defect_total={_format_finding_value(item.get('defect_total'))}")
            parts.append(f"defect_avg={_format_finding_value(item.get('defect_avg'))}")

        group = working_df[working_df[delay_col].astype(str) == str(item["delay_reason"])]
        context_cols = [column for column in [asset_col, line_col, shift_col, maintenance_col] if column]
        if context_cols and loss_col:
            worst = group.sort_values(loss_col, ascending=False).head(1)
            if not worst.empty:
                parts.append(f"worst_row={_row_label(_records_for_model(worst, limit=1)[0])}")
        findings.append(" | ".join(parts) + ".")

    return findings


def _build_spreadsheet_findings(df: Any, profile: Dict[str, Any]) -> List[str]:
    findings: List[str] = []
    findings.extend(_build_numeric_comparison_findings(df))
    findings.extend(_build_cost_delay_findings(df))
    action_plan = _build_concrete_action_plan(df)
    findings.extend(_format_action_plan_findings(action_plan))
    operational = profile.get("operational_summary", {})

    planned = operational.get("planned_vs_actual")
    if planned:
        findings.append(
            "Production shortfall: planned_total="
            f"{_format_finding_value(planned.get('planned_total'))}, actual_total="
            f"{_format_finding_value(planned.get('actual_total'))}, shortfall_total="
            f"{_format_finding_value(planned.get('shortfall_total'))}, average_attainment_pct="
            f"{_format_finding_value(planned.get('average_attainment_pct'))}."
        )

    for key, label in [
        ("downtime", "Downtime"),
        ("defects", "Defects"),
        ("vibration", "Vibration"),
        ("estimated_loss", "Estimated loss"),
    ]:
        metric = operational.get(key)
        if not metric:
            continue
        findings.append(
            f"{label}: total={_format_finding_value(metric.get('total'))}, "
            f"average={_format_finding_value(metric.get('average'))}, max={_format_finding_value(metric.get('max'))}, "
            f"first={_format_finding_value(metric.get('first'))}, last={_format_finding_value(metric.get('last'))}."
        )

    for key, label in [
        ("delay_reason_counts", "Delay reasons"),
        ("maintenance_status_counts", "Maintenance status"),
        ("priority_counts", "Priority"),
    ]:
        counts = operational.get(key)
        if counts:
            top_counts = ", ".join(f"{name}={count}" for name, count in list(counts.items())[:5])
            findings.append(f"{label}: {top_counts}.")

    group_summary = profile.get("group_summary", {})
    for group_name in ["production_line", "asset_id", "facility", "shift"]:
        if group_name not in group_summary:
            continue
        group_bits = []
        for metric_name in [
            "downtime_total",
            "defect_total",
            "estimated_loss_total",
            "actual_shortfall_total",
        ]:
            label = _top_group_label(profile, group_name, metric_name)
            if label:
                group_bits.append(label)
        if group_bits:
            findings.append(f"Worst {group_name} signals: " + " | ".join(group_bits[:3]) + ".")

    high_risk_rows = profile.get("highest_risk_rows", {})
    for key, label in [
        ("highest_downtime_rows", "Highest downtime row"),
        ("highest_defect_rows", "Highest defect row"),
        ("highest_vibration_rows", "Highest vibration row"),
        ("highest_loss_rows", "Highest loss row"),
        ("largest_actual_vs_planned_shortfall_rows", "Largest production shortfall row"),
    ]:
        rows = high_risk_rows.get(key) or []
        if rows:
            findings.append(f"{label}: {_row_label(rows[0])}.")

    findings.append(
        "Specific next-action guidance: tie actions to the worst production_line, asset_id, shift, "
        "delay_reason, maintenance_status, downtime, defect_count, vibration, and estimated_loss values above."
    )
    return findings[:24]


# ==================== Request/Response Schemas ====================

class NLPQueryRequest(BaseModel):
    """Request for NLP query to correlation AI"""
    query: str = Field(..., description="Natural language query")
    context: Optional[Dict[str, Any]] = Field(default={}, description="Additional context for the query")
    include_domains: Optional[List[str]] = Field(default=None, description="Specific domains to analyze")
    auto_integrate: bool = Field(default=True, description="Auto-integrate with registries/Kanban")


class NLPQueryResponse(BaseModel):
    """Response from NLP correlation AI query"""
    query: str
    analysis: str
    domains_analyzed: List[str]
    risk_score: float
    recommended_actions: List[Dict[str, Any]]
    kanban_tasks: List[Dict[str, Any]]
    compliance_implications: Optional[List[str]]
    integration_result: Optional[Dict[str, List[str]]]


class IntakeUploadRequest(BaseModel):
    """Request for Intake Inbox data upload"""
    title: str = Field(..., description="Title of the uploaded data")
    description: Optional[str] = Field(default="", description="Description of the data")
    data_type: str = Field(..., description="Type of data: spreadsheet, report, image, document")
    category: Optional[str] = Field(default="general", description="Category for organization")


class IntakeAnalysisRequest(BaseModel):
    """Request for analyzing uploaded data"""
    intake_id: UUID = Field(..., description="Intake item ID")
    query: Optional[str] = Field(default=None, description="Specific query for analysis")
    auto_integrate: bool = Field(default=True, description="Auto-integrate with registries/Kanban")


class IntakeItem(BaseModel):
    """Intake Inbox item"""
    id: UUID
    title: str
    description: str
    data_type: str
    category: str
    file_name: Optional[str]
    status: str
    analysis_result: Optional[Dict[str, Any]]
    created_at: datetime
    analyzed_at: Optional[datetime]


class IntakeListResponse(BaseModel):
    """Response for listing intake items"""
    items: List[IntakeItem]
    total: int


# ==================== NLP Query Endpoints ====================

@router.post("/query", response_model=NLPQueryResponse)
async def nlp_query(
    request: NLPQueryRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Process natural language query to correlation AI.
    
    This endpoint:
    1. Parses the natural language query
    2. Determines relevant domains from the query
    3. Runs correlation AI analysis
    4. Returns actionable insights and recommendations
    5. Optionally auto-integrates with registries and Kanban
    """
    logger.info("nlp_query_received", user_id=str(current_user.id), query=request.query)
    
    # Parse query to extract domains and context
    domains = request.include_domains or _extract_domains_from_query(request.query)
    
    # Create a correlation scenario from the NLP query
    from app.models.domain_interaction import CorrelationScenario, DomainType, OperationalMetric
    from datetime import datetime
    
    domain_types = [DomainType(d) for d in domains] if domains else []
    
    # Extract operational context from query
    operational_metrics = _extract_metrics_from_query(request.query, request.context)
    
    scenario = CorrelationScenario(
        scenario_id=f"nlp-{current_user.id}-{int(datetime.now(timezone.utc).timestamp())}",
        active_domains=domain_types,
        ingested_metrics=operational_metrics,
        domain_links=[]
    )
    
    # Run correlation AI analysis
    analysis_result = await correlation_ai_engine.analyze_scenario(
        scenario,
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        auto_integrate=request.auto_integrate
    )
    
    # Extract results
    correlation_analysis = analysis_result.get("predicted_root_cause", "")
    risk_score = analysis_result.get("risk_score", 0)
    recommended_tasks = analysis_result.get("target_kanban_tasks", [])
    recommended_commands = analysis_result.get("remediation_commands", [])
    compliance_implications = analysis_result.get("compliance_implications")
    integration_result = analysis_result.get("integration_result")
    
    return NLPQueryResponse(
        query=request.query,
        analysis=correlation_analysis,
        domains_analyzed=domains,
        risk_score=risk_score,
        recommended_actions=recommended_commands,
        kanban_tasks=recommended_tasks,
        compliance_implications=compliance_implications,
        integration_result=integration_result
    )


@router.post("/chat")
async def nlp_chat(
    message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Chat interface for correlation AI interaction.
    
    This provides a conversational interface for interacting with the correlation AI.
    Maintains conversation context for multi-turn queries.
    """
    logger.info("nlp_chat_message", user_id=str(current_user.id), message=message)
    
    # Process message with conversation history
    context = {
        "conversation_history": conversation_history or [],
        "user_id": str(current_user.id)
    }
    
    # Parse message as NLP query
    nlp_request = NLPQueryRequest(
        query=message,
        context=context,
        auto_integrate=False  # Don't auto-integrate in chat mode
    )
    
    # Run analysis
    response = await nlp_query(nlp_request, None, db, current_user)
    
    # Format as chat response
    chat_response = {
        "role": "assistant",
        "content": f"{response.analysis}\n\nRisk Score: {response.risk_score}/100",
        "analysis": response.analysis,
        "risk_score": response.risk_score,
        "domains": response.domains_analyzed,
        "actions": response.recommended_actions,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    return chat_response


# ==================== Intake Inbox Endpoints ====================

@router.post("/intake/upload")
async def upload_to_intake(
    file: UploadFile = File(...),
    title: str = None,
    description: str = "",
    data_type: str = "document",
    category: str = "general",
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Upload data to Intake Inbox for correlation AI analysis.
    
    Supports:
    - Spreadsheets (CSV, Excel)
    - Reports (PDF, Word)
    - Images (PNG, JPG) - if Gemma4 supports vision
    - Documents (Text files)
    """
    logger.info(
        "intake_upload",
        user_id=str(current_user.id),
        filename=file.filename,
        data_type=data_type
    )
    
    # Validate file type
    allowed_extensions = {
        "spreadsheet": [".csv", ".xlsx", ".xls"],
        "report": [".pdf", ".docx", ".doc"],
        "image": [".png", ".jpg", ".jpeg"],
        "document": [".txt", ".md"]
    }
    
    file_ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if data_type in allowed_extensions and f".{file_ext}" not in allowed_extensions[data_type]:
        raise HTTPException(status_code=400, detail=f"Invalid file extension for type {data_type}")
    
    # Read file content
    content = await file.read()
    
    # Process file content based on type
    processed_data = await _process_uploaded_file(content, data_type, file.filename)
    
    # Store in database
    import base64
    file_content_b64 = base64.b64encode(content).decode('utf-8')
    
    intake_item = IntakeItem(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        title=title or file.filename,
        description=description,
        data_type=data_type,
        category=category,
        file_name=file.filename,
        file_content=file_content_b64,
        processed_data=processed_data,
        status="pending"
    )
    
    db.add(intake_item)
    await db.commit()
    await db.refresh(intake_item)
    
    logger.info("intake_upload_complete", intake_id=str(intake_item.id))
    
    return {
        "id": str(intake_item.id),
        "title": intake_item.title,
        "description": intake_item.description,
        "data_type": intake_item.data_type,
        "category": intake_item.category,
        "file_name": intake_item.file_name,
        "status": intake_item.status,
        "created_at": intake_item.created_at.isoformat(),
        "analyzed_at": intake_item.analyzed_at.isoformat() if intake_item.analyzed_at else None,
        # Processing-time estimate so the UI can prompt the user before analysis.
        "estimated_seconds": processed_data.get("estimated_seconds"),
        "requires_confirmation": processed_data.get("requires_confirmation", False),
        "tab_count": processed_data.get("tab_count"),
        "page_count": processed_data.get("page_count"),
        "section_count": processed_data.get("section_count"),
        "truncated": processed_data.get("truncated", False),
    }


@router.post("/intake/analyze")
async def analyze_intake(
    intake_id: UUID,
    query: Optional[str] = None,
    auto_integrate: bool = True,
    mode: str = "window",
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Analyze uploaded data in Intake Inbox with correlation AI.

    For spreadsheets/workbooks this:
    1. Retrieves the uploaded item and decodes the stored file
    2. Parses ALL tabs into DataFrames
    3. Builds cross-tab-linked CorrelationScenarios (mode: window|tab|row)
    4. Runs the correlation AI engine over every scenario (full coverage)
    5. Aggregates per-domain findings and cross-tab correlations
    6. Persists the combined analysis on the intake item
    """
    logger.info(
        "intake_analysis",
        user_id=str(current_user.id),
        intake_id=str(intake_id),
        mode=mode,
    )

    # Retrieve the intake item
    result = await db.execute(
        select(IntakeItemModel).where(
            IntakeItemModel.id == intake_id,
            IntakeItemModel.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Intake item not found")

    # Route by data type: each path builds cross-linked scenarios and runs the
    # correlation AI engine over every scenario (full coverage).
    try:
        if item.data_type == "spreadsheet" and item.file_content:
            analysis_result = await _analyze_spreadsheet_item(
                item, query, auto_integrate, mode, db, current_user
            )
        elif item.data_type in ("report", "document") and item.file_content:
            analysis_result = await _analyze_document_item(
                item, query, auto_integrate, mode, db, current_user
            )
        elif item.data_type == "image" and item.file_content:
            analysis_result = await _analyze_image_item(
                item, query, auto_integrate, mode, db, current_user
            )
        else:
            # Last-resort: NLP query over a default/explicit prompt.
            default_query = query or (
                f"Analyze the uploaded {item.data_type} '{item.title}' for operational "
                f"anomalies and correlations"
            )
            nlp_request = NLPQueryRequest(query=default_query, auto_integrate=auto_integrate)
            response = await nlp_query(nlp_request, None, db, current_user)
            analysis_result = {
                "intake_id": str(intake_id),
                "analysis": response.analysis,
                "risk_score": response.risk_score,
                "domains_analyzed": response.domains_analyzed,
                "recommended_actions": response.recommended_actions,
                "kanban_tasks": response.kanban_tasks,
                "compliance_implications": response.compliance_implications,
                "integration_result": response.integration_result,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("intake_analysis_failed", error=str(e), intake_id=str(intake_id))
        item.status = "error"
        item.analysis_result = {"error": str(e)}
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    # Persist results on the intake item
    item.analysis_result = analysis_result
    item.status = "analyzed"
    item.analyzed_at = datetime.now(timezone.utc)
    await db.commit()

    analysis_result["analyzed_at"] = item.analyzed_at.isoformat()
    return analysis_result


async def _analyze_spreadsheet_item(
    item: "IntakeItemModel",
    query: Optional[str],
    auto_integrate: bool,
    mode: str,
    db: AsyncSession,
    current_user: User,
) -> Dict[str, Any]:
    """Parse all tabs of a stored workbook and run correlation analysis per scenario."""
    import base64
    import io
    import pandas as pd
    from app.services.spreadsheet_scenario_builder import build_scenarios
    from app.services.spreadsheet_domain_mapper import map_workbook_domains

    # Decode the stored file
    content = base64.b64decode(item.file_content)
    filename = item.file_name or "upload.xlsx"

    if filename.endswith(".csv"):
        tabs = {"Sheet1": pd.read_csv(io.BytesIO(content))}
    elif filename.endswith((".xlsx", ".xls")):
        tabs = pd.read_excel(io.BytesIO(content), sheet_name=None)
    else:
        tabs = {"Sheet1": pd.read_csv(io.StringIO(content.decode("utf-8")))}

    # Domain mapping summary for transparency
    tab_columns = {name: [str(c) for c in df.columns] for name, df in tabs.items()}
    mapping = map_workbook_domains(tab_columns)

    # Build and analyze scenarios (full coverage)
    source_id = f"intake-{item.id}"
    domains_seen: List[str] = []
    risk_scores: List[float] = []
    kanban_tasks: List[Dict[str, Any]] = []
    commands: List[Dict[str, Any]] = []
    compliance: List[str] = []
    cross_tab_links = 0
    scenario_count = 0
    per_scenario: List[Dict[str, Any]] = []

    for scenario in build_scenarios(tabs, mode=mode, source_id=source_id):
        scenario_count += 1
        if len(scenario.active_domains) >= 2:
            cross_tab_links += len(scenario.domain_links)
        analysis = await correlation_ai_engine.analyze_scenario(
            scenario,
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            # Avoid creating hundreds of registry items; integrate only the summary later
            auto_integrate=False,
        )
        for d in scenario.active_domains:
            if d.value not in domains_seen:
                domains_seen.append(d.value)
        risk_scores.append(analysis.get("risk_score", 0.0))
        for t in (analysis.get("target_kanban_tasks") or []):
            if t not in kanban_tasks:
                kanban_tasks.append(t)
        for c in (analysis.get("remediation_commands") or []):
            if c not in commands:
                commands.append(c)
        for ci in (analysis.get("compliance_implications") or []):
            if ci not in compliance:
                compliance.append(ci)
        # Keep a bounded sample of per-scenario detail
        if len(per_scenario) < 100:
            per_scenario.append({
                "scenario_id": scenario.scenario_id,
                "domains": [d.value for d in scenario.active_domains],
                "risk_score": analysis.get("risk_score"),
                "root_cause": analysis.get("predicted_root_cause"),
            })

    overall_risk = round(max(risk_scores), 1) if risk_scores else 0.0
    summary_text = (
        f"Analyzed {scenario_count} cross-tab scenarios across "
        f"{len(domains_seen)} domains ({', '.join(domains_seen) or 'none'}). "
        f"{cross_tab_links} cross-domain links detected. "
        f"Peak risk score {overall_risk}/100."
    )

    return {
        "intake_id": str(item.id),
        "analysis": summary_text,
        "mode": mode,
        "tab_count": len(tabs),
        "tab_domain_mapping": mapping.to_dict(),
        "scenarios_analyzed": scenario_count,
        "cross_domain_links": cross_tab_links,
        "domains_analyzed": domains_seen,
        "risk_score": overall_risk,
        "recommended_actions": commands[:20],
        "kanban_tasks": kanban_tasks[:20],
        "compliance_implications": compliance or None,
        "scenario_samples": per_scenario,
    }


async def _run_scenarios(
    scenarios,
    db: AsyncSession,
    current_user: User,
    sample_cap: int = 100,
) -> Dict[str, Any]:
    """Run the correlation AI engine over an iterable of scenarios and aggregate.

    Shared by spreadsheet/document/image/cross-file analyzers.
    """
    domains_seen: List[str] = []
    risk_scores: List[float] = []
    kanban_tasks: List[Dict[str, Any]] = []
    commands: List[Dict[str, Any]] = []
    compliance: List[str] = []
    cross_links = 0
    scenario_count = 0
    per_scenario: List[Dict[str, Any]] = []

    for scenario in scenarios:
        scenario_count += 1
        if len(scenario.active_domains) >= 2:
            cross_links += len(scenario.domain_links)
        analysis = await correlation_ai_engine.analyze_scenario(
            scenario,
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            auto_integrate=False,
        )
        for d in scenario.active_domains:
            if d.value not in domains_seen:
                domains_seen.append(d.value)
        risk_scores.append(analysis.get("risk_score", 0.0))
        for t in (analysis.get("target_kanban_tasks") or []):
            if t not in kanban_tasks:
                kanban_tasks.append(t)
        for c in (analysis.get("remediation_commands") or []):
            if c not in commands:
                commands.append(c)
        for ci in (analysis.get("compliance_implications") or []):
            if ci not in compliance:
                compliance.append(ci)
        if len(per_scenario) < sample_cap:
            per_scenario.append({
                "scenario_id": scenario.scenario_id,
                "domains": [d.value for d in scenario.active_domains],
                "risk_score": analysis.get("risk_score"),
                "root_cause": analysis.get("predicted_root_cause"),
            })

    return {
        "scenario_count": scenario_count,
        "cross_links": cross_links,
        "domains_seen": domains_seen,
        "risk_score": round(max(risk_scores), 1) if risk_scores else 0.0,
        "kanban_tasks": kanban_tasks,
        "commands": commands,
        "compliance": compliance,
        "per_scenario": per_scenario,
    }


async def _analyze_document_item(
    item: "IntakeItemModel",
    query: Optional[str],
    auto_integrate: bool,
    mode: str,
    db: AsyncSession,
    current_user: User,
) -> Dict[str, Any]:
    """Parse a stored PDF/DOCX/text document and run cross-section correlation."""
    import base64
    from app.services.document_domain_mapper import map_document_domains
    from app.services import document_scenario_builder

    content = base64.b64decode(item.file_content)
    filename = (item.file_name or "document").lower()

    if filename.endswith(".pdf"):
        from app.services.pdf_parser import parse_pdf_structure
        structure = parse_pdf_structure(content, item.file_name)
    elif filename.endswith((".docx", ".doc")):
        from app.services.docx_parser import parse_docx_structure
        structure = parse_docx_structure(content, item.file_name)
    else:
        # Plain text: wrap as a single section.
        text = content.decode("utf-8", errors="replace")
        structure = {
            "type": item.data_type,
            "sections": [{"section_id": 0, "heading": item.title, "level": 0,
                          "paragraphs": text.split("\n"), "tables": []}],
            "shared_keys": (item.processed_data or {}).get("shared_keys", []),
        }

    mapping = map_document_domains(structure)
    # Section/page mode is the document default; reuse provided mode if valid.
    doc_mode = mode if mode in ("section", "document", "table") else "section"
    source_id = f"intake-{item.id}"
    scenarios = document_scenario_builder.build_scenarios(
        structure, mapping=mapping, mode=doc_mode, source_id=source_id,
    )
    agg = await _run_scenarios(scenarios, db, current_user)

    unit = "pages" if structure.get("pages") is not None else "sections"
    count = structure.get("page_count", structure.get("section_count", 0))
    summary_text = (
        f"Analyzed {agg['scenario_count']} cross-{unit[:-1]} scenarios across "
        f"{len(agg['domains_seen'])} domains "
        f"({', '.join(agg['domains_seen']) or 'none'}). "
        f"{agg['cross_links']} cross-domain links detected across {count} {unit}. "
        f"Peak risk score {agg['risk_score']}/100."
    )
    return {
        "intake_id": str(item.id),
        "analysis": summary_text,
        "mode": doc_mode,
        "document_type": structure.get("subtype"),
        f"{unit}_count": count,
        "truncated": structure.get("truncated", False),
        "section_domain_mapping": mapping.to_dict(),
        "scenarios_analyzed": agg["scenario_count"],
        "cross_domain_links": agg["cross_links"],
        "domains_analyzed": agg["domains_seen"],
        "shared_keys": structure.get("shared_keys", []),
        "risk_score": agg["risk_score"],
        "recommended_actions": agg["commands"][:20],
        "kanban_tasks": agg["kanban_tasks"][:20],
        "compliance_implications": agg["compliance"] or None,
        "scenario_samples": agg["per_scenario"],
    }


async def _analyze_image_item(
    item: "IntakeItemModel",
    query: Optional[str],
    auto_integrate: bool,
    mode: str,
    db: AsyncSession,
    current_user: User,
) -> Dict[str, Any]:
    """Extract text from a stored image and run correlation on it."""
    import base64
    from app.services.image_text_extractor import extract_text_from_image
    from app.services.image_domain_mapper import map_image_domains
    from app.services import image_scenario_builder

    content = base64.b64decode(item.file_content)
    # Prefer cached extraction from upload; re-extract if absent.
    processed = item.processed_data or {}
    if processed.get("extracted_text"):
        extraction = dict(processed)
    else:
        extraction = extract_text_from_image(content, item.file_name or "image.png")
    extraction.setdefault("image_id", str(item.id))
    extractions = [extraction]

    mapping = map_image_domains(extractions)
    img_mode = mode if mode in ("image", "batch") else "image"
    source_id = f"intake-{item.id}"
    scenarios = image_scenario_builder.build_scenarios(
        extractions, mapping=mapping, mode=img_mode, source_id=source_id,
    )
    agg = await _run_scenarios(scenarios, db, current_user)

    note = extraction.get("note")
    summary_text = (
        f"Analyzed image '{item.title}' via {extraction.get('extraction_method', 'none')}. "
        f"{agg['scenario_count']} scenario(s), domains "
        f"({', '.join(agg['domains_seen']) or 'none'}). "
        f"Peak risk score {agg['risk_score']}/100."
    )
    if note:
        summary_text += f" Note: {note}"

    return {
        "intake_id": str(item.id),
        "analysis": summary_text,
        "mode": img_mode,
        "extraction_method": extraction.get("extraction_method"),
        "extracted_text_chars": len(extraction.get("extracted_text", "")),
        "image_domain_mapping": mapping.to_dict(),
        "scenarios_analyzed": agg["scenario_count"],
        "cross_domain_links": agg["cross_links"],
        "domains_analyzed": agg["domains_seen"],
        "shared_keys": extraction.get("shared_keys", []),
        "risk_score": agg["risk_score"],
        "recommended_actions": agg["commands"][:20],
        "kanban_tasks": agg["kanban_tasks"][:20],
        "compliance_implications": agg["compliance"] or None,
        "scenario_samples": agg["per_scenario"],
    }


def build_source_descriptor(
    source_id: str,
    data_type: str,
    file_name: Optional[str],
    processed_data: Optional[Dict[str, Any]],
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Derive a {source_id, data_type, file_name, domains, keys, summary} descriptor
    from any source's processed_data, for cross-file correlation. Reused by both
    Intake items and session data sources."""
    from app.services.shared_key_detector import (
        extract_keys_from_filename, extract_keys_from_records,
    )
    processed = processed_data or {}
    domains: List[str] = []
    keys: List[str] = list(processed.get("shared_keys") or [])
    keys.extend(extract_keys_from_filename(file_name))

    if data_type == "spreadsheet":
        from app.services.spreadsheet_domain_mapper import map_workbook_domains
        from app.services.multi_spreadsheet_correlator import keys_from_processed_spreadsheet
        tabs = processed.get("tabs") or []
        tab_columns = {t.get("name", f"tab{i}"): t.get("column_names", [])
                       for i, t in enumerate(tabs)}
        if tab_columns:
            mapping = map_workbook_domains(tab_columns)
            domains = [d.value for d in mapping.active_domains]
        keys.extend(keys_from_processed_spreadsheet(processed))
        for t in tabs:
            keys.extend(extract_keys_from_records(t.get("sample_data") or []))
    elif data_type in ("report", "document"):
        from app.services.document_domain_mapper import (
            map_document_domains, map_section_to_domain,
        )
        mapping = map_document_domains(processed)
        domains = [d.value for d in mapping.active_domains]
        if not domains and processed.get("content"):
            d = map_section_to_domain({"text": processed.get("content")})
            if d:
                domains = [d.value]
    elif data_type == "image":
        from app.services.image_domain_mapper import map_image_to_domain
        d = map_image_to_domain(processed.get("extracted_text", ""), processed.get("metadata"))
        if d:
            domains = [d.value]

    return {
        "source_id": str(source_id),
        "data_type": data_type,
        "file_name": file_name,
        "domains": domains,
        "keys": list(dict.fromkeys([k for k in keys if k])),
        "summary": {"title": title or file_name, "data_type": data_type},
    }


def _source_descriptor_from_item(item: "IntakeItemModel") -> Dict[str, Any]:
    """Cross-file source descriptor for a stored Intake item."""
    return build_source_descriptor(
        str(item.id), item.data_type, item.file_name, item.processed_data, item.title,
    )


class CrossCorrelationRequest(BaseModel):
    """Request to correlate multiple intake items across files."""
    intake_ids: List[UUID] = Field(..., description="Intake item IDs to correlate")
    shared_keys: Optional[List[str]] = Field(
        None, description="Manual shared keys (merged with auto-detected keys)")
    auto_integrate: bool = Field(default=True)


@router.post("/intake/cross-correlate")
async def cross_correlate_intake(
    request: CrossCorrelationRequest,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Correlate MULTIPLE intake items (PDF, DOCX, image, spreadsheet) across files.

    1. Loads each intake item the user owns
    2. Derives per-source domains + shared keys (filename, metadata, content)
    3. Auto-detects correlation groups (optionally forced by manual shared_keys)
    4. Builds cross-file CorrelationScenarios linking sources by shared keys
    5. Runs the correlation AI engine over every group and aggregates findings
    """
    from app.services.cross_file_scenario_builder import build_cross_file_scenarios

    logger.info("intake_cross_correlate", user_id=str(current_user.id),
                count=len(request.intake_ids))

    result = await db.execute(
        select(IntakeItemModel).where(
            IntakeItemModel.id.in_(request.intake_ids),
            IntakeItemModel.user_id == current_user.id,
        )
    )
    items = result.scalars().all()
    if len(items) < 2:
        raise HTTPException(
            status_code=400,
            detail="Provide at least 2 owned intake items to cross-correlate",
        )

    descriptors = [_source_descriptor_from_item(it) for it in items]
    scenarios = build_cross_file_scenarios(
        descriptors, manual_keys=request.shared_keys, source_id="cross-file",
    )
    agg = await _run_scenarios(scenarios, db, current_user)

    summary_text = (
        f"Cross-correlated {len(items)} files into {agg['scenario_count']} group(s) "
        f"across {len(agg['domains_seen'])} domains "
        f"({', '.join(agg['domains_seen']) or 'none'}). "
        f"{agg['cross_links']} cross-domain links detected. "
        f"Peak risk score {agg['risk_score']}/100."
    )
    if agg["scenario_count"] == 0:
        summary_text = (
            f"No shared keys linked the {len(items)} files. Provide manual "
            f"shared_keys to force correlation, or verify the files reference "
            f"common identifiers (asset_id, order number, date, etc.)."
        )

    return {
        "intake_ids": [str(it.id) for it in items],
        "analysis": summary_text,
        "files": [{"source_id": d["source_id"], "file_name": d["file_name"],
                   "data_type": d["data_type"], "domains": d["domains"],
                   "keys": d["keys"]} for d in descriptors],
        "manual_shared_keys": request.shared_keys or [],
        "correlation_groups": agg["scenario_count"],
        "cross_domain_links": agg["cross_links"],
        "domains_analyzed": agg["domains_seen"],
        "risk_score": agg["risk_score"],
        "recommended_actions": agg["commands"][:20],
        "kanban_tasks": agg["kanban_tasks"][:20],
        "compliance_implications": agg["compliance"] or None,
        "scenario_samples": agg["per_scenario"],
    }


@router.get("/intake/list")
async def list_intake_items(
    limit: int = Query(50, ge=1, description="Maximum rows to return."),
    offset: int = Query(0, ge=0, description="Rows to skip."),
    status: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db)
):
    """
    List items in Intake Inbox.
    
    Returns paginated list of uploaded data items with their analysis status.
    """
    logger.info(
        "intake_list",
        user_id=str(current_user.id),
        limit=limit,
        offset=offset,
        status=status
    )
    
    # Build query
    query = select(IntakeItemModel).where(IntakeItemModel.user_id == current_user.id)
    
    if status:
        query = query.where(IntakeItemModel.status == status)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Get items
    query = query.order_by(IntakeItemModel.created_at.desc())
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(item.id),
                "title": item.title,
                "description": item.description,
                "data_type": item.data_type,
                "category": item.category,
                "file_name": item.file_name,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
                "analyzed_at": item.analyzed_at.isoformat() if item.analyzed_at else None
            }
            for item in items
        ],
        "total": total
    }


@router.get("/intake/{intake_id}")
async def get_intake_item(
    intake_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db)
):
    """
    Get details of a specific Intake Inbox item.
    """
    logger.info("intake_get_item", user_id=str(current_user.id), intake_id=str(intake_id))
    
    # `IntakeItemModel`, NOT `IntakeItem` (FS-431). This module defines a Pydantic
    # `IntakeItem` at module scope for the response body, and imports the ORM class as
    # `IntakeItemModel`; passing the Pydantic class to `select()` raises, so this endpoint
    # returned 500 to every caller. The sibling read at ~line 1334 has always used the right
    # one, which is what makes the shadowing so easy to miss: both names exist, both look
    # plausible at the call site, and only one is a mapped class.
    from sqlalchemy import select
    query = select(IntakeItemModel).where(
        IntakeItemModel.id == intake_id,
        IntakeItemModel.user_id == current_user.id
    )
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Intake item not found")
    
    return {
        "id": str(item.id),
        "title": item.title,
        "description": item.description,
        "data_type": item.data_type,
        "category": item.category,
        "file_name": item.file_name,
        "status": item.status,
        "processed_data": item.processed_data,
        "analysis_result": item.analysis_result,
        "created_at": item.created_at.isoformat(),
        "analyzed_at": item.analyzed_at.isoformat() if item.analyzed_at else None
    }


# ==================== Helper Functions ====================

def _extract_domains_from_query(query: str) -> List[str]:
    """Extract relevant domains from natural language query"""
    query_lower = query.lower()
    
    domain_keywords = {
        "LOGISTICS_FLEET": ["trailer", "truck", "dock", "yard", "detention", "carrier", "driver", "shipment", "logistics"],
        "MAINTENANCE": ["maintenance", "equipment", "vibration", "temperature", "work order", "technician", "repair"],
        "PRODUCTION_OEE": ["production", "oee", "throughput", "cycle time", "quality rate", "asset", "cell", "manufacturing"],
        "QUALITY_CONTROL": ["quality", "inspection", "defect", "first pass yield", "capa", "non-conformance"],
        "SAFETY": ["safety", "incident", "security", "hazard", "compliance", "near-miss", "accident"],
        "COMPLIANCE_REGISTRIES": ["compliance", "audit", "regulatory", "iso", "osha", "dot", "violation"],
        "WAREHOUSE_MANAGEMENT": ["warehouse", "inventory", "slot", "storage", "fulfillment", "stockout"],
        "SYSTEM_INFRASTRUCTURE": ["network", "database", "latency", "infrastructure", "availability", "error rate", "it"]
    }
    
    detected_domains = []
    for domain, keywords in domain_keywords.items():
        if any(keyword in query_lower for keyword in keywords):
            detected_domains.append(domain)
    
    return detected_domains


def _extract_metrics_from_query(query: str, context: Dict[str, Any]) -> List:
    """Extract operational metrics from query and context.

    Returns OperationalMetric objects matching the domain_interaction schema
    (endpoint + payload_snapshot + timestamp).
    """
    from app.models.domain_interaction import OperationalMetric
    from datetime import datetime

    metrics = []
    timestamp = datetime.now(timezone.utc).isoformat()

    # Extract numeric values from query into a single metric payload
    import re
    numbers = re.findall(r'\d+\.?\d*', query)

    payload: Dict[str, Any] = {"source": "nlp_query"}
    if numbers:
        for i, num in enumerate(numbers):
            payload[f"query_metric_{i}"] = float(num)

    # Add scalar context values
    if context:
        for key, value in context.items():
            if isinstance(value, (int, float)):
                payload[f"context_{key}"] = float(value)

    if len(payload) > 1:  # more than just "source"
        metrics.append(OperationalMetric(
            endpoint="/nlp/query",
            payload_snapshot=payload,
            timestamp=timestamp,
        ))

    return metrics


def _profile_single_sheet(sheet_name: str, df: Any) -> Dict[str, Any]:
    """Build a full tab profile. Profiling errors are captured per sheet, not fatal."""
    tab: Dict[str, Any] = {
        "name": str(sheet_name),
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": [str(c) for c in df.columns.tolist()],
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
    }
    if df.empty:
        tab.update({
            "sample_data": [],
            "tail_sample_data": [],
            "summary": {},
            "linking_metadata": _build_linking_metadata(df),
            "full_sheet_profile": {},
            "concrete_action_plan": [],
            "numeric_comparisons": [],
            "distilled_findings": [],
        })
        return tab

    try:
        linking = _build_linking_metadata(df)
        full_sheet_profile = _build_spreadsheet_profile(df)
        concrete_action_plan = _build_concrete_action_plan(df)
        numeric_comparisons = _build_numeric_comparison_findings(df)
        distilled_findings = (
            _build_spreadsheet_findings(df, full_sheet_profile)
            if full_sheet_profile else []
        )
        tab.update({
            "sample_data": _records_for_model(df, limit=5),
            "tail_sample_data": _records_for_model(df.tail(5), limit=5),
            "summary": _numeric_describe(df),
            "linking_metadata": linking,
            "full_sheet_profile": full_sheet_profile,
            "concrete_action_plan": concrete_action_plan,
            "numeric_comparisons": numeric_comparisons,
            "distilled_findings": distilled_findings,
        })
    except Exception as exc:
        logger.warning("sheet_profile_failed", sheet=str(sheet_name), error=str(exc))
        tab.update({
            "parse_error": str(exc),
            "sample_data": _records_for_model(df, limit=5),
            "tail_sample_data": [],
            "summary": _numeric_describe(df),
            "linking_metadata": _build_linking_metadata(df),
            "full_sheet_profile": {},
            "concrete_action_plan": [],
            "numeric_comparisons": [],
            "distilled_findings": [
                f"Sheet '{sheet_name}' uploaded; detailed profiling skipped: {exc}"
            ],
        })
    return tab


def _merge_workbook_tab_outputs(tabs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-tab analysis into workbook-level fields used by chat."""
    if not tabs:
        return {
            "columns": 0,
            "column_names": [],
            "sample_data": [],
            "tail_sample_data": [],
            "summary": {},
            "full_sheet_profile": {},
            "concrete_action_plan": [],
            "numeric_comparisons": [],
            "distilled_findings": [],
        }

    ok_tabs = [tab for tab in tabs if not tab.get("parse_error")]
    primary = ok_tabs[0] if ok_tabs else tabs[0]
    richest = max(ok_tabs or tabs, key=lambda tab: tab.get("rows") or 0)

    all_findings: List[str] = []
    for tab in tabs:
        prefix = f"[{tab['name']}] " if len(tabs) > 1 else ""
        if tab.get("parse_error"):
            all_findings.append(f"{prefix}profiling skipped: {tab['parse_error']}")
        for finding in tab.get("distilled_findings") or []:
            all_findings.append(f"{prefix}{finding}")

    all_actions: List[Dict[str, Any]] = []
    for tab in ok_tabs:
        for action in tab.get("concrete_action_plan") or []:
            tagged = dict(action)
            tagged["sheet"] = tab["name"]
            all_actions.append(tagged)

    def action_sort_key(action: Dict[str, Any]) -> tuple:
        facts = action.get("why_it_matters") or {}
        return (
            facts.get("total_estimated_cost") or 0,
            facts.get("total_downtime") or 0,
            facts.get("total_defects") or 0,
            facts.get("average_vibration") or 0,
        )

    all_actions.sort(key=action_sort_key, reverse=True)

    merged_profile = dict(primary.get("full_sheet_profile") or {})
    if len(tabs) > 1:
        merged_profile["workbook_tab_count"] = len(tabs)
        merged_profile["per_tab_summaries"] = [
            {
                "name": tab["name"],
                "rows": tab.get("rows", 0),
                "columns": tab.get("columns", 0),
                "parse_error": tab.get("parse_error"),
                "operational_summary": (tab.get("full_sheet_profile") or {}).get("operational_summary") or {},
            }
            for tab in tabs
        ]

    return {
        "primary_tab": primary.get("name"),
        "columns": richest.get("columns", 0),
        "column_names": richest.get("column_names", []),
        "sample_data": richest.get("sample_data", []),
        "tail_sample_data": richest.get("tail_sample_data", []),
        "summary": richest.get("summary", {}),
        "full_sheet_profile": merged_profile,
        "concrete_action_plan": all_actions[:6],
        "numeric_comparisons": sum((tab.get("numeric_comparisons") or [] for tab in ok_tabs), [])[:12],
        "distilled_findings": all_findings[:24],
    }


async def _process_uploaded_file(content: bytes, data_type: str, filename: str) -> Dict[str, Any]:
    """Process uploaded file content based on type"""
    
    try:
        if data_type == "spreadsheet":
            # For CSV/Excel files
            import pandas as pd
            import io

            # Read ALL tabs/sheets. CSV is a single implicit sheet.
            if filename.lower().endswith('.csv'):
                sheets = {"Sheet1": pd.read_csv(io.BytesIO(content))}
            elif filename.lower().endswith('.xlsx'):
                # sheet_name=None returns an ordered dict of {sheet_name: DataFrame}
                sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, engine='openpyxl')
            elif filename.lower().endswith('.xls'):
                sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, engine='xlrd')
            else:
                sheets = {"Sheet1": pd.read_csv(io.StringIO(content.decode('utf-8')))}

            tabs = []
            total_rows = 0
            tab_linking: List[Dict[str, Any]] = []
            for sheet_name, df in sheets.items():
                total_rows += len(df)
                tab = _profile_single_sheet(str(sheet_name), df)
                tabs.append(tab)
                tab_linking.append(tab.get("linking_metadata") or {})

            workbook = _merge_workbook_tab_outputs(tabs)
            workbook_linking = _merge_workbook_linking(tab_linking)
            return {
                "type": "spreadsheet",
                "tab_count": len(tabs),
                "rows": total_rows,
                "tab_names": [t["name"] for t in tabs],
                "tabs": tabs,
                "linking_metadata": workbook_linking,
                "filename": filename,
                "primary_tab": workbook.get("primary_tab"),
                # Workbook-level fields aggregate every sheet.
                "columns": workbook.get("columns", 0),
                "column_names": workbook.get("column_names", []),
                "sample_data": workbook.get("sample_data", []),
                "tail_sample_data": workbook.get("tail_sample_data", []),
                "summary": workbook.get("summary", {}),
                "full_sheet_profile": workbook.get("full_sheet_profile", {}),
                "concrete_action_plan": workbook.get("concrete_action_plan", []),
                "numeric_comparisons": workbook.get("numeric_comparisons", []),
                "distilled_findings": workbook.get("distilled_findings", []),
            }
        
        elif data_type == "image":
            # Vision-model text extraction (Gemma/Gemini) with graceful fallback.
            from app.services.image_text_extractor import extract_text_from_image
            extraction = extract_text_from_image(content, filename or "image.png")
            extraction["size"] = len(content)
            return extraction

        elif data_type in ["report", "document"]:
            lower = (filename or "").lower()
            if lower.endswith(".pdf"):
                from app.services.pdf_parser import parse_pdf_structure
                structure = parse_pdf_structure(content, filename)
                structure["size"] = len(content)
                return structure
            if lower.endswith((".docx", ".doc")):
                from app.services.docx_parser import parse_docx_structure
                structure = parse_docx_structure(content, filename)
                structure["size"] = len(content)
                return structure
            # Plain-text document: keep simple content + shared keys.
            from app.services.shared_key_detector import (
                extract_keys_from_text, extract_keys_from_filename,
            )
            text_content = content.decode("utf-8", errors="replace")
            keys = extract_keys_from_filename(filename) + extract_keys_from_text(text_content)
            return {
                "type": data_type,
                "subtype": "text",
                "size": len(content),
                "content": text_content,
                "word_count": len(text_content.split()),
                "shared_keys": list(dict.fromkeys([k for k in keys if k])),
                "estimated_seconds": round(max(len(text_content) / 50000, 0.2), 1),
            }
        
        else:
            return {
                "type": data_type,
                "size": len(content)
            }
    
    except Exception as e:
        logger.error("file_processing_error", error=str(e), data_type=data_type)
        return {
            "type": data_type,
            "size": len(content),
            "error": str(e)
        }
