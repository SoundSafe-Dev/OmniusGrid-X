"""Deterministic, lineage-aware evidence tables for operational correlation.

This module deliberately keeps matching separate from language-model inference.
It turns rows from uploaded tables into an auditable common table, proposes safe
join plans, and reports the quality of the *evidence join*.  A high score means
the records were linked cleanly; it does not claim that one operational metric
caused another.

The public API accepts plain dictionaries and pandas DataFrames so intake
adapters can use it without a database migration::

    sources = [{
        "source_id": "production.xlsx",
        "tables": {"Production": [{"Asset ID": "MX-101", ...}]},
    }]
    candidates = profile_join_candidates(sources)
    preview = build_evidence_table(sources, join_plan=candidates[0])

``preview`` is JSON-serialisable and includes a stable source/table/row
lineage record for every matched and unmatched row.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from hashlib import sha256
from itertools import combinations
import json
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.services.shared_key_detector import normalize_column_header, normalize_key


# The aliases are intentionally conservative.  A value is only automatically
# joined when the column describes the same operational entity or context.
_COLUMN_ALIASES = {
    "asset": "asset_id",
    "asset_id": "asset_id",
    "asset_number": "asset_id",
    "equipment": "asset_id",
    "equipment_id": "asset_id",
    "equipment_number": "asset_id",
    "machine": "asset_id",
    "machine_id": "asset_id",
    "machine_number": "asset_id",
    "trailer": "trailer_id",
    "trailer_id": "trailer_id",
    "vehicle": "trailer_id",
    "vehicle_id": "trailer_id",
    "facility": "facility",
    "facility_id": "facility",
    "facility_code": "facility",
    "plant": "facility",
    "plant_id": "facility",
    "site": "facility",
    "site_id": "facility",
    "location": "facility",
    "line": "line_id",
    "line_id": "line_id",
    "line_number": "line_id",
    "production_line": "line_id",
    "production_line_id": "line_id",
    "shift": "shift",
    "shift_name": "shift",
    "date": "event_time",
    "event_date": "event_time",
    "production_date": "event_time",
    "posting_date": "event_time",
    "order_date": "event_time",
    "time": "event_time",
    "datetime": "event_time",
    "timestamp": "event_time",
    "event_time": "event_time",
    "event_timestamp": "event_time",
    "recorded_at": "event_time",
    "created_at": "event_time",
    "work_order": "work_order_id",
    "work_order_id": "work_order_id",
    "work_order_number": "work_order_id",
    "wo_number": "work_order_id",
    "order": "order_id",
    "order_id": "order_id",
    "order_number": "order_id",
    "purchase_order": "purchase_order_id",
    "purchase_order_id": "purchase_order_id",
    "po_number": "purchase_order_id",
    "sales_order": "sales_order_id",
    "sales_order_id": "sales_order_id",
    "so_number": "sales_order_id",
    "invoice": "invoice_id",
    "invoice_id": "invoice_id",
    "invoice_number": "invoice_id",
    "lot": "lot_id",
    "lot_id": "lot_id",
    "lot_number": "lot_id",
    "batch": "batch_id",
    "batch_id": "batch_id",
    "batch_number": "batch_id",
    "shipment": "shipment_id",
    "shipment_id": "shipment_id",
    "tracking_number": "tracking_id",
    "tracking_id": "tracking_id",
}

# These keys identify a concrete operational thing or transaction.  Time,
# shift, facility, and line add useful context but are not safe automatic
# anchors on their own: two assets can absolutely share the same shift.
_STRONG_ANCHORS = {
    "asset_id",
    "trailer_id",
    "work_order_id",
    "order_id",
    "purchase_order_id",
    "sales_order_id",
    "invoice_id",
    "lot_id",
    "batch_id",
    "shipment_id",
    "tracking_id",
}
_CONTEXT_KEYS = {"facility", "line_id", "shift", "event_time"}
_IDENTIFIER_KEYS = _STRONG_ANCHORS | {"facility", "line_id", "shift"}
_TEMPORAL_KEY = "event_time"

_MAX_COMPOSITE_CONTEXT_KEYS = 3
_DEFAULT_MAX_MATCH_PAIRS = 100_000

# Entity rollups are a *presentation of source facts*, not another join.  Keep
# them bounded independently from the pairwise evidence preview so a wide
# workbook cannot turn a review response into an unbounded aggregation blob.
_DEFAULT_MAX_ROLLUPS = 300
_DEFAULT_MAX_METRICS_PER_TABLE = 16
_DEFAULT_MAX_GROUPS_PER_ROLLUP = 25
_DEFAULT_ROLLUP_LINEAGE_SAMPLE = 3

# Numeric structural columns are not operational measurements.  They must not
# become a synthetic "total" merely because a spreadsheet happened to encode
# them as numbers.
_ROLLUP_NON_METRIC_CANONICAL_NAMES = {
    "id", "record_id", "source_id", "row_id", "row_number", "index",
    "sequence", "year", "month", "day", "week", "quarter",
}


@dataclass(frozen=True)
class EvidenceLineage:
    """Stable coordinates for one source row."""

    source_id: str
    source_key: str
    source_name: str
    table_name: str
    table_key: str
    row_number: int
    row_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_key": self.source_key,
            "source_name": self.source_name,
            "table_name": self.table_name,
            "table_key": self.table_key,
            "row_number": self.row_number,
            "row_id": self.row_id,
        }


@dataclass
class _ColumnProfile:
    name: str
    canonical_name: str
    logical_type: str
    semantic_type: str
    non_null_count: int
    null_count: int
    distinct_count: int
    examples: List[Any]

    @property
    def completeness(self) -> float:
        total = self.non_null_count + self.null_count
        return self.non_null_count / total if total else 0.0

    @property
    def uniqueness(self) -> float:
        return self.distinct_count / self.non_null_count if self.non_null_count else 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "canonical_name": self.canonical_name,
            "logical_type": self.logical_type,
            "semantic_type": self.semantic_type,
            "non_null_count": self.non_null_count,
            "null_count": self.null_count,
            "completeness": round(self.completeness, 6),
            "distinct_count": self.distinct_count,
            "uniqueness": round(self.uniqueness, 6),
            "examples": [_json_safe(value) for value in self.examples],
        }


@dataclass
class _EvidenceRecord:
    lineage: EvidenceLineage
    values: Dict[str, Any]


@dataclass
class _EvidenceTable:
    source_id: str
    source_key: str
    source_name: str
    table_name: str
    table_key: str
    records: List[_EvidenceRecord]
    columns: List[_ColumnProfile]

    @property
    def ref(self) -> Dict[str, str]:
        return {
            "source_id": self.source_id,
            "source_key": self.source_key,
            "source_name": self.source_name,
            "table_name": self.table_name,
            "table_key": self.table_key,
        }


def _canonical_identifier(value: Any, fallback: str) -> str:
    normalized = normalize_column_header(value)
    return normalized or fallback


def _canonical_column_name(value: Any) -> str:
    normalized = normalize_column_header(value)
    return _COLUMN_ALIASES.get(normalized, normalized or "unnamed_field")


def _is_missing(value: Any) -> bool:
    """Treat Python, NumPy, and pandas scalar missing values as null safely."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    try:
        result = value != value
        # numpy.bool_ deliberately supports bool(); pandas.NA does not.
        return bool(result) if isinstance(result, (bool, int)) else False
    except (TypeError, ValueError):
        return False


def _json_safe(value: Any) -> Any:
    """Convert scalar values to JSON-friendly, deterministic representations."""
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        value = _as_utc(value)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    # numpy/pandas scalars normally expose item().  Do not import either
    # dependency just to serialise an otherwise simple intake record.
    try:
        item = value.item()  # type: ignore[attr-defined]
        if item is not value:
            return _json_safe(item)
    except (AttributeError, TypeError, ValueError):
        pass
    return str(value)


def _as_utc(value: datetime) -> datetime:
    """Canonicalise timestamps; naive source timestamps are treated as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_temporal(value: Any) -> Tuple[Optional[datetime], bool]:
    """Return ``(UTC datetime, source_was_date_only)`` when a value is temporal."""
    if _is_missing(value):
        return None, False
    if isinstance(value, datetime):
        return _as_utc(value), False
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc), True
    if not isinstance(value, str):
        return None, False

    text = value.strip()
    if not text:
        return None, False
    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso_text)
        return _as_utc(parsed), "T" not in text and " " not in text
    except ValueError:
        pass
    try:
        parsed_date = date.fromisoformat(text)
        return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc), True
    except ValueError:
        pass
    for pattern in (
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d/%m/%Y",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
    ):
        try:
            parsed = datetime.strptime(text, pattern)
            has_time = "%H" in pattern
            return parsed.replace(tzinfo=timezone.utc), not has_time
        except ValueError:
            continue
    return None, False


def _numeric_value(value: Any) -> Optional[float]:
    if _is_missing(value) or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or re.match(r"^[+-]?0\d+", text):
            # Values with leading zeros are overwhelmingly identifiers.
            return None
        try:
            result = float(text)
            return result if math.isfinite(result) else None
        except ValueError:
            return None
    try:
        scalar = value.item()  # type: ignore[attr-defined]
        if scalar is not value:
            return _numeric_value(scalar)
    except (AttributeError, TypeError, ValueError):
        pass
    return None


def _infer_scalar_type(value: Any, canonical_name: str) -> str:
    if _is_missing(value):
        return "null"
    if canonical_name in _IDENTIFIER_KEYS:
        return "string"
    if canonical_name == _TEMPORAL_KEY:
        parsed, date_only = _parse_temporal(value)
        if parsed is not None:
            return "date" if date_only else "datetime"
    if isinstance(value, bool) or (isinstance(value, str) and value.strip().lower() in {"true", "false", "yes", "no"}):
        return "boolean"
    numeric = _numeric_value(value)
    if numeric is not None:
        if float(numeric).is_integer():
            return "integer"
        return "number"
    parsed, date_only = _parse_temporal(value)
    if parsed is not None:
        return "date" if date_only else "datetime"
    return "string"


def _combine_types(types: Iterable[str]) -> str:
    observed = {item for item in types if item != "null"}
    if not observed:
        return "null"
    if observed <= {"integer"}:
        return "integer"
    if observed <= {"integer", "number"}:
        return "number"
    if observed <= {"date"}:
        return "date"
    if observed <= {"date", "datetime"}:
        return "datetime"
    if len(observed) == 1:
        return next(iter(observed))
    return "mixed"


def _semantic_type(canonical_name: str) -> str:
    if canonical_name == _TEMPORAL_KEY:
        return "temporal"
    if canonical_name in _STRONG_ANCHORS:
        return "entity_identifier"
    if canonical_name in {"facility", "line_id"}:
        return "operational_context"
    if canonical_name == "shift":
        return "time_context"
    return "attribute"


def _table_rows(value: Any) -> List[Dict[str, Any]]:
    """Coerce common tabular representations into a list of plain row dicts."""
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        try:
            rows = value.to_dict(orient="records")
            return [dict(row) for row in rows if isinstance(row, Mapping)]
        except (TypeError, ValueError):
            pass
    if isinstance(value, Mapping):
        for key in ("rows", "records", "data"):
            if key in value:
                return _table_rows(value[key])
        # A single object can still be one evidence row.
        return [dict(value)]
    if isinstance(value, (str, bytes)):
        raise TypeError("A table must be rows or a DataFrame, not a string")
    if isinstance(value, Iterable):
        rows = []
        for item in value:
            if isinstance(item, Mapping):
                rows.append(dict(item))
            else:
                raise TypeError("Every table row must be a mapping")
        return rows
    raise TypeError("Unsupported table representation")


def _source_tables(source: Mapping[str, Any]) -> Mapping[str, Any]:
    tables = source.get("tables") or source.get("sheets") or source.get("tabs")
    if isinstance(tables, Mapping):
        return tables
    for row_key in ("rows", "records", "data"):
        if row_key in source:
            table_name = str(source.get("table_name") or source.get("name") or "rows")
            return {table_name: source[row_key]}
    return {}


def _profile_rows(rows: Sequence[Mapping[str, Any]]) -> List[_ColumnProfile]:
    names: List[str] = []
    for row in rows:
        for name in row:
            text = str(name)
            if text not in names:
                names.append(text)

    profiles: List[_ColumnProfile] = []
    for name in names:
        canonical_name = _canonical_column_name(name)
        values = [row.get(name) for row in rows]
        observed = [value for value in values if not _is_missing(value)]
        encoded_values = {
            _canonical_value(value, canonical_name, strategy="exact", bucket_minutes=None)
            for value in observed
        }
        encoded_values.discard(None)
        examples: List[Any] = []
        for value in observed:
            if value not in examples:
                examples.append(value)
            if len(examples) >= 3:
                break
        profiles.append(_ColumnProfile(
            name=name,
            canonical_name=canonical_name,
            logical_type=_combine_types(_infer_scalar_type(value, canonical_name) for value in values),
            semantic_type=_semantic_type(canonical_name),
            non_null_count=len(observed),
            null_count=len(values) - len(observed),
            distinct_count=len(encoded_values),
            examples=examples,
        ))
    return profiles


def _normalize_sources(sources: Sequence[Mapping[str, Any]]) -> List[_EvidenceTable]:
    """Flatten input sources/tables while preserving canonical lineage."""
    tables: List[_EvidenceTable] = []
    source_key_counts: Counter = Counter()
    for source_index, raw_source in enumerate(sources, start=1):
        raw_source_id = str(raw_source.get("source_id") or raw_source.get("id") or "source-%d" % source_index)
        source_name = str(raw_source.get("source_name") or raw_source.get("file_name") or raw_source.get("filename") or raw_source_id)
        source_key_base = _canonical_identifier(raw_source_id, "source_%d" % source_index)
        source_key_counts[source_key_base] += 1
        source_key = source_key_base
        if source_key_counts[source_key_base] > 1:
            source_key = "%s_%d" % (source_key_base, source_key_counts[source_key_base])

        table_key_counts: Counter = Counter()
        for table_index, (raw_table_name, raw_rows) in enumerate(_source_tables(raw_source).items(), start=1):
            table_name = str(raw_table_name)
            base_table_key = _canonical_identifier(table_name, "table_%d" % table_index)
            table_key_counts[base_table_key] += 1
            table_key = base_table_key
            if table_key_counts[base_table_key] > 1:
                table_key = "%s_%d" % (base_table_key, table_key_counts[base_table_key])
            rows = _table_rows(raw_rows)
            records: List[_EvidenceRecord] = []
            for row_number, row in enumerate(rows, start=1):
                lineage = EvidenceLineage(
                    source_id=raw_source_id,
                    source_key=source_key,
                    source_name=source_name,
                    table_name=table_name,
                    table_key=table_key,
                    row_number=row_number,
                    row_id="%s:%s:%d" % (source_key, table_key, row_number),
                )
                records.append(_EvidenceRecord(lineage=lineage, values=dict(row)))
            tables.append(_EvidenceTable(
                source_id=raw_source_id,
                source_key=source_key,
                source_name=source_name,
                table_name=table_name,
                table_key=table_key,
                records=records,
                columns=_profile_rows([record.values for record in records]),
            ))
    return tables


def infer_typed_schema(rows: Any) -> Dict[str, Any]:
    """Infer a compact, typed schema for a list of row mappings or DataFrame."""
    normalized_rows = _table_rows(rows)
    profiles = _profile_rows(normalized_rows)
    return {
        "row_count": len(normalized_rows),
        "columns": [profile.as_dict() for profile in profiles],
        "timezone_assumption": "Naive timestamps are interpreted as UTC.",
    }


def _profile_evidence_tables(tables: Sequence[_EvidenceTable]) -> Dict[str, Any]:
    return {
        "source_count": len({table.source_key for table in tables}),
        "table_count": len(tables),
        "tables": [
            {
                **table.ref,
                "row_count": len(table.records),
                "schema": {
                    "row_count": len(table.records),
                    "columns": [column.as_dict() for column in table.columns],
                    "timezone_assumption": "Naive timestamps are interpreted as UTC.",
                },
            }
            for table in tables
        ],
    }


def _rollup_metric_is_structural(column: _ColumnProfile) -> bool:
    """Return whether a numeric column is structural rather than a measure."""

    canonical_name = column.canonical_name
    token = normalize_column_header(canonical_name)
    if canonical_name in _IDENTIFIER_KEYS or canonical_name in _CONTEXT_KEYS:
        return True
    if canonical_name in _ROLLUP_NON_METRIC_CANONICAL_NAMES:
        return True
    return (
        token.endswith("_id")
        or token.endswith("_code")
        or token.endswith("_number")
        or token.startswith("row_")
    )


def _rollup_aggregation(metric_name: Any) -> str:
    """Choose a conservative, declared aggregate for a metric label.

    Additive quantities (units, counts, minutes, cost) retain ``sum``. Rates,
    ratios, condition readings, and scores use ``mean`` so a rollup cannot
    quietly turn a percentage or temperature into a meaningless total.
    """

    token = normalize_column_header(metric_name)
    if any(
        marker in token
        for marker in (
            "rate", "percent", "percentage", "ratio", "ppm", "oee",
            "yield", "score", "temperature", "pressure", "vibration",
            "speed", "cycle_time", "availability", "utilization",
        )
    ):
        return "mean"
    return "sum"


def _rollup_dimension_sets(table: _EvidenceTable) -> List[Tuple[str, Tuple[str, ...]]]:
    """Return safe operational entity grains available in one source table.

    An asset identifier is scoped by facility when the source supplies both;
    similarly, shift is scoped by its available facility and line context. This
    prevents a generic "Day" shift or reused asset code from becoming a
    floor-wide entity by accident.
    """

    available = _best_columns_by_canonical(table)
    dimensions: List[Tuple[str, Tuple[str, ...]]] = [("company", tuple())]
    has_facility = "facility" in available
    has_line = "line_id" in available
    if has_facility:
        dimensions.append(("facility", ("facility",)))
    if has_line:
        dimensions.append(("line", tuple(name for name in ("facility", "line_id") if name in available)))
    if "asset_id" in available:
        dimensions.append(("asset", tuple(name for name in ("facility", "asset_id") if name in available)))
    if "shift" in available:
        dimensions.append(("shift", tuple(name for name in ("facility", "line_id", "shift") if name in available)))
    return dimensions


def _rollup_metric_specs(table: _EvidenceTable) -> List[Dict[str, Any]]:
    """Return source-table-local numeric metric specs without pooling fields.

    A normalized long-form table is partitioned by its declared metric name and
    unit before aggregation. Wide tables retain one rollup metric per numeric
    source column. In both cases the source table remains an immutable
    aggregation boundary.
    """

    best_columns = _best_columns_by_canonical(table)
    value_column = best_columns.get("value")
    metric_name_column = best_columns.get("metric_name")
    unit_column = best_columns.get("unit")
    if value_column is not None and value_column.logical_type in {"integer", "number"}:
        partitions: Dict[Tuple[str, str], List[_EvidenceRecord]] = defaultdict(list)
        display_values: Dict[Tuple[str, str], Tuple[Any, Any]] = {}
        for record in table.records:
            if _numeric_value(record.values.get(value_column.name)) is None:
                continue
            metric_value = (
                record.values.get(metric_name_column.name)
                if metric_name_column is not None else value_column.name
            )
            if _is_missing(metric_value):
                metric_value = value_column.name
            unit_value = record.values.get(unit_column.name) if unit_column is not None else None
            key = (
                json.dumps(_json_safe(metric_value), sort_keys=True, default=str),
                json.dumps(_json_safe(unit_value), sort_keys=True, default=str),
            )
            partitions[key].append(record)
            display_values.setdefault(key, (metric_value, unit_value))
        specs: List[Dict[str, Any]] = []
        for key in sorted(partitions):
            metric_value, unit_value = display_values[key]
            specs.append({
                "source_column": value_column.name,
                "canonical_name": "value",
                "metric_name": _json_safe(metric_value),
                "unit": _json_safe(unit_value),
                "aggregation": _rollup_aggregation(metric_value),
                "metric_type": "long_form",
                "records": partitions[key],
            })
        return specs[:_DEFAULT_MAX_METRICS_PER_TABLE]

    specs = []
    for column in table.columns:
        if column.logical_type not in {"integer", "number"} or _rollup_metric_is_structural(column):
            continue
        specs.append({
            "source_column": column.name,
            "canonical_name": column.canonical_name,
            "metric_name": _json_safe(column.name),
            "unit": None,
            "aggregation": _rollup_aggregation(column.canonical_name),
            "metric_type": "wide_column",
            "records": table.records,
        })
    specs.sort(key=lambda spec: (str(spec["canonical_name"]), str(spec["source_column"])))
    return specs[:_DEFAULT_MAX_METRICS_PER_TABLE]


def _rollup_time_range(
    accumulator: Dict[str, Any],
    record: _EvidenceRecord,
    temporal_column: Optional[_ColumnProfile],
) -> None:
    if temporal_column is None:
        return
    parsed, _date_only = _parse_temporal(record.values.get(temporal_column.name))
    if parsed is None:
        return
    earliest = accumulator.get("earliest_event_time")
    latest = accumulator.get("latest_event_time")
    if earliest is None or parsed < earliest:
        accumulator["earliest_event_time"] = parsed
    if latest is None or parsed > latest:
        accumulator["latest_event_time"] = parsed


def _rollup_datetime(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _rollup_entity_label(level: str, entity: Mapping[str, Any]) -> str:
    if not entity:
        return "All usable records in this source table"
    return " · ".join("%s=%s" % (name, _json_safe(value)) for name, value in entity.items())


def _build_source_table_rollup(
    table: _EvidenceTable,
    metric_spec: Mapping[str, Any],
    entity_level: str,
    dimensions: Sequence[str],
    best_columns: Mapping[str, _ColumnProfile],
    *,
    max_groups: int,
    lineage_sample_limit: int,
) -> Dict[str, Any]:
    """Aggregate exactly one metric inside exactly one source table."""

    groups: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    skipped_missing_entity = 0
    skipped_missing_metric = 0
    temporal_column = best_columns.get(_TEMPORAL_KEY)
    source_column = str(metric_spec["source_column"])
    aggregation = str(metric_spec["aggregation"])
    for record in metric_spec.get("records") or []:
        value = _numeric_value(record.values.get(source_column))
        if value is None:
            skipped_missing_metric += 1
            continue
        entity: Dict[str, Any] = {}
        key_values: List[str] = []
        incomplete_entity = False
        for dimension in dimensions:
            column = best_columns.get(dimension)
            if column is None:
                incomplete_entity = True
                break
            raw_value = record.values.get(column.name)
            normalized_value = _canonical_value(
                raw_value,
                dimension,
                strategy="exact",
                bucket_minutes=None,
            )
            if normalized_value is None:
                incomplete_entity = True
                break
            key_values.append(normalized_value)
            entity[dimension] = _json_safe(raw_value)
        if incomplete_entity:
            skipped_missing_entity += 1
            continue
        key = tuple(key_values)
        accumulator = groups.get(key)
        if accumulator is None:
            accumulator = {
                "entity": entity,
                "sum": 0.0,
                "source_record_count": 0,
                "lineage_sample": [],
                "earliest_event_time": None,
                "latest_event_time": None,
            }
            groups[key] = accumulator
        accumulator["sum"] += value
        accumulator["source_record_count"] += 1
        if len(accumulator["lineage_sample"]) < lineage_sample_limit:
            accumulator["lineage_sample"].append(record.lineage.as_dict())
        _rollup_time_range(accumulator, record, temporal_column)

    materialized_groups: List[Dict[str, Any]] = []
    for key, accumulator in groups.items():
        count = int(accumulator["source_record_count"])
        value = accumulator["sum"] / count if aggregation == "mean" and count else accumulator["sum"]
        entity = dict(accumulator["entity"])
        materialized_groups.append({
            "entity": entity,
            "entity_label": _rollup_entity_label(entity_level, entity),
            "value": round(float(value), 8),
            "source_record_count": count,
            "event_time_range": {
                "min": _rollup_datetime(accumulator["earliest_event_time"]),
                "max": _rollup_datetime(accumulator["latest_event_time"]),
            },
            "lineage_sample": list(accumulator["lineage_sample"]),
            "entity_key": list(key),
        })
    materialized_groups.sort(
        key=lambda group: (-abs(float(group["value"])), group["entity_label"])
    )
    truncated = len(materialized_groups) > max_groups
    kept_groups = materialized_groups[:max_groups]
    rollup_token = "|".join((
        table.source_key,
        table.table_key,
        str(metric_spec["source_column"]),
        json.dumps(_json_safe(metric_spec.get("metric_name")), sort_keys=True, default=str),
        json.dumps(_json_safe(metric_spec.get("unit")), sort_keys=True, default=str),
        entity_level,
        ",".join(dimensions),
    ))
    return {
        "rollup_id": "rollup-%s" % sha256(rollup_token.encode("utf-8")).hexdigest()[:16],
        "source": table.ref,
        "entity_level": entity_level,
        "entity_dimensions": list(dimensions),
        "metric": {
            "source_column": metric_spec["source_column"],
            "canonical_name": metric_spec["canonical_name"],
            "metric_name": metric_spec["metric_name"],
            "unit": metric_spec["unit"],
            "aggregation": aggregation,
            "metric_type": metric_spec["metric_type"],
        },
        "groups": kept_groups,
        "group_count": len(materialized_groups),
        "groups_truncated": truncated,
        "excluded_missing_entity_record_count": skipped_missing_entity,
        "excluded_missing_metric_record_count": skipped_missing_metric,
        "interpretation": (
            "This is a %s of one metric inside one source table. It is not pooled with other files or tables."
            % aggregation
        ),
    }


def build_entity_rollups(
    sources: Sequence[Mapping[str, Any]],
    *,
    max_rollups: int = _DEFAULT_MAX_ROLLUPS,
    max_groups_per_rollup: int = _DEFAULT_MAX_GROUPS_PER_ROLLUP,
    lineage_sample_limit: int = _DEFAULT_ROLLUP_LINEAGE_SAMPLE,
) -> Dict[str, Any]:
    """Build bounded, source-table-scoped company/entity rollups.

    The result deliberately has no cross-table or cross-file sum. A "company"
    group means all usable rows for one metric in one source table; an "asset"
    group is calculated only from rows carrying that asset (and facility when
    supplied). This makes it impossible for a file-level total to be silently
    presented as an asset-level value.
    """

    if max_rollups <= 0:
        raise ValueError("max_rollups must be greater than zero")
    if max_groups_per_rollup <= 0:
        raise ValueError("max_groups_per_rollup must be greater than zero")
    if lineage_sample_limit <= 0:
        raise ValueError("lineage_sample_limit must be greater than zero")

    tables = _normalize_sources(sources)
    per_table_limit = max(1, max_rollups // max(1, len(tables)))
    rollups: List[Dict[str, Any]] = []
    table_summaries: List[Dict[str, Any]] = []
    truncated = False
    for table in tables:
        best_columns = _best_columns_by_canonical(table)
        metric_specs = _rollup_metric_specs(table)
        dimension_sets = _rollup_dimension_sets(table)
        table_rollup_count = 0
        for metric_spec in metric_specs:
            for entity_level, dimensions in dimension_sets:
                if table_rollup_count >= per_table_limit or len(rollups) >= max_rollups:
                    truncated = True
                    break
                rollups.append(_build_source_table_rollup(
                    table,
                    metric_spec,
                    entity_level,
                    dimensions,
                    best_columns,
                    max_groups=max_groups_per_rollup,
                    lineage_sample_limit=lineage_sample_limit,
                ))
                table_rollup_count += 1
            if table_rollup_count >= per_table_limit or len(rollups) >= max_rollups:
                break
        if metric_specs and table_rollup_count < len(metric_specs) * len(dimension_sets):
            truncated = True
        table_summaries.append({
            **table.ref,
            "metric_count_considered": len(metric_specs),
            "entity_levels_available": [level for level, _dimensions in dimension_sets],
            "rollup_count": table_rollup_count,
            "rollups_truncated": bool(metric_specs and table_rollup_count < len(metric_specs) * len(dimension_sets)),
        })

    return {
        "source_table_scoped": True,
        "cross_table_pooling": False,
        "scope_contract": {
            "company": "All usable records for one metric in one source table; never a pooled total across files or tables.",
            "asset": "Only rows with the cited asset identifier are included; facility is part of the identity whenever the table supplies it.",
            "line": "Only rows with the cited line identifier are included; facility is part of the identity whenever the table supplies it.",
            "shift": "Only rows with the cited shift are included, with available facility and line context retained.",
            "metric_boundary": "Metrics and units remain separate. Values from different source columns, tables, files, or units are never summed together.",
        },
        "rollup_count": len(rollups),
        "rollups": rollups,
        "tables": table_summaries,
        "truncated": truncated,
        "limits": {
            "max_rollups": max_rollups,
            "max_rollups_per_table": per_table_limit,
            "max_metrics_per_table": _DEFAULT_MAX_METRICS_PER_TABLE,
            "max_groups_per_rollup": max_groups_per_rollup,
            "lineage_sample_limit": lineage_sample_limit,
        },
    }


def profile_evidence_sources(sources: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return typed schemas and canonical table references for all input sources."""
    return _profile_evidence_tables(_normalize_sources(sources))


def _best_columns_by_canonical(table: _EvidenceTable) -> Dict[str, _ColumnProfile]:
    """Resolve aliases; favour populated, semantically exact source columns."""
    selected: Dict[str, _ColumnProfile] = {}
    for column in table.columns:
        current = selected.get(column.canonical_name)
        if current is None:
            selected[column.canonical_name] = column
            continue
        candidate_score = (column.completeness, column.uniqueness, column.name == column.canonical_name)
        current_score = (current.completeness, current.uniqueness, current.name == current.canonical_name)
        if candidate_score > current_score:
            selected[column.canonical_name] = column
    return selected


def _type_compatible(left: _ColumnProfile, right: _ColumnProfile) -> bool:
    if left.canonical_name == _TEMPORAL_KEY:
        return left.logical_type in {"date", "datetime", "mixed", "string"} and right.logical_type in {
            "date", "datetime", "mixed", "string"
        }
    left_type = left.logical_type
    right_type = right.logical_type
    if left_type == "null" or right_type == "null":
        return False
    if left_type == right_type:
        return True
    if {left_type, right_type} <= {"integer", "number"}:
        return True
    # Identifier aliases often arrive as numeric values in one export and text
    # in another.  The canonical identifier normalizer is deterministic.
    if left.canonical_name in _IDENTIFIER_KEYS and right.canonical_name in _IDENTIFIER_KEYS:
        return True
    return False


def _canonical_value(
    value: Any,
    canonical_name: str,
    strategy: str,
    bucket_minutes: Optional[int],
    date_granularity: bool = False,
    aliases: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    if _is_missing(value):
        return None

    if canonical_name == _TEMPORAL_KEY:
        parsed, date_only = _parse_temporal(value)
        if parsed is None:
            return None
        if strategy == "time_bucket":
            if date_granularity or date_only:
                return "day:%s" % parsed.date().isoformat()
            minutes = int(bucket_minutes or 60)
            if minutes <= 0:
                raise ValueError("time_bucket_minutes must be greater than zero")
            epoch_minutes = int(parsed.timestamp() // 60)
            bucket_start = epoch_minutes - (epoch_minutes % minutes)
            bucket_time = datetime.fromtimestamp(bucket_start * 60, tz=timezone.utc)
            return "bucket:%dm:%s" % (minutes, bucket_time.isoformat())
        return parsed.isoformat() if not date_only else parsed.date().isoformat()

    if canonical_name in _IDENTIFIER_KEYS:
        result = normalize_key(value)
    elif isinstance(value, bool):
        result = "true" if value else "false"
    else:
        numeric = _numeric_value(value)
        if numeric is not None:
            result = ("%.12g" % numeric).upper()
        else:
            result = normalize_key(value)

    if aliases:
        # Allow a reviewed entity-resolution dictionary in a manual plan. Both
        # raw and normalized alias keys are accepted; no fuzzy matching occurs.
        raw_alias = aliases.get(str(value))
        normalized_alias = aliases.get(result)
        replacement = raw_alias if raw_alias is not None else normalized_alias
        if replacement is not None:
            result = normalize_key(replacement)
    return result or None


def _field_spec(
    canonical_name: str,
    left: _ColumnProfile,
    right: _ColumnProfile,
    strategy: str,
    time_bucket_minutes: Optional[int],
) -> Dict[str, Any]:
    is_temporal = canonical_name == _TEMPORAL_KEY
    return {
        "canonical_name": canonical_name,
        "left_column": left.name,
        "right_column": right.name,
        "semantic_type": left.semantic_type,
        "strategy": "time_bucket" if is_temporal and strategy == "time_bucket" else "exact",
        "time_bucket_minutes": time_bucket_minutes if is_temporal and strategy == "time_bucket" else None,
    }


def _plan_id(left: _EvidenceTable, right: _EvidenceTable, keys: Sequence[Mapping[str, Any]]) -> str:
    token = "|".join([
        left.source_key,
        left.table_key,
        right.source_key,
        right.table_key,
        ";".join(
            "%s:%s:%s:%s:%s:%s" % (
                key["canonical_name"],
                key["left_column"],
                key["right_column"],
                key["strategy"],
                key.get("time_bucket_minutes") or "",
                int(bool(key.get("date_granularity"))),
            )
            for key in keys
        ),
    ])
    return "join-%s" % sha256(token.encode("utf-8")).hexdigest()[:16]


def _key_for_record(
    record: _EvidenceRecord,
    key_specs: Sequence[Mapping[str, Any]],
    side: str,
    aliases_by_field: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Optional[Tuple[str, ...]]:
    values: List[str] = []
    for spec in key_specs:
        column = str(spec["%s_column" % side])
        canonical_name = str(spec["canonical_name"])
        strategy = str(spec.get("strategy") or "exact")
        aliases = (aliases_by_field or {}).get(canonical_name)
        value = _canonical_value(
            record.values.get(column),
            canonical_name,
            strategy=strategy,
            bucket_minutes=spec.get("time_bucket_minutes"),
            date_granularity=bool(spec.get("date_granularity")),
            aliases=aliases,
        )
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def _join_indexes(
    left: _EvidenceTable,
    right: _EvidenceTable,
    key_specs: Sequence[Mapping[str, Any]],
    aliases_by_field: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Tuple[Dict[Tuple[str, ...], List[_EvidenceRecord]], Dict[Tuple[str, ...], List[_EvidenceRecord]]]:
    left_index: Dict[Tuple[str, ...], List[_EvidenceRecord]] = defaultdict(list)
    right_index: Dict[Tuple[str, ...], List[_EvidenceRecord]] = defaultdict(list)
    for record in left.records:
        key = _key_for_record(record, key_specs, "left", aliases_by_field)
        if key is not None:
            left_index[key].append(record)
    for record in right.records:
        key = _key_for_record(record, key_specs, "right", aliases_by_field)
        if key is not None:
            right_index[key].append(record)
    return dict(left_index), dict(right_index)


def _join_metrics(
    left: _EvidenceTable,
    right: _EvidenceTable,
    key_specs: Sequence[Mapping[str, Any]],
    aliases_by_field: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    left_index, right_index = _join_indexes(left, right, key_specs, aliases_by_field)
    shared_keys = sorted(set(left_index).intersection(right_index))
    matched_pairs = sum(len(left_index[key]) * len(right_index[key]) for key in shared_keys)
    matched_left = sum(len(left_index[key]) for key in shared_keys)
    matched_right = sum(len(right_index[key]) for key in shared_keys)
    max_pairs_per_key = max(
        (len(left_index[key]) * len(right_index[key]) for key in shared_keys), default=0
    )
    many_to_many = sum(
        1 for key in shared_keys if len(left_index[key]) > 1 and len(right_index[key]) > 1
    )
    one_to_many = sum(
        1 for key in shared_keys if len(left_index[key]) == 1 and len(right_index[key]) > 1
    )
    many_to_one = sum(
        1 for key in shared_keys if len(left_index[key]) > 1 and len(right_index[key]) == 1
    )
    left_keyed = sum(len(rows) for rows in left_index.values())
    right_keyed = sum(len(rows) for rows in right_index.values())
    matched_unique = max(matched_left, matched_right, 1)
    selectivity = min(1.0, matched_unique / matched_pairs) if matched_pairs else 0.0
    return {
        "left_index": left_index,
        "right_index": right_index,
        "shared_keys": shared_keys,
        "matched_pair_count": matched_pairs,
        "matched_left_record_count": matched_left,
        "matched_right_record_count": matched_right,
        "left_keyed_record_count": left_keyed,
        "right_keyed_record_count": right_keyed,
        "left_key_completeness": (left_keyed / len(left.records)) if left.records else 0.0,
        "right_key_completeness": (right_keyed / len(right.records)) if right.records else 0.0,
        "left_match_coverage": (matched_left / len(left.records)) if left.records else 0.0,
        "right_match_coverage": (matched_right / len(right.records)) if right.records else 0.0,
        "key_overlap_count": len(shared_keys),
        "key_union_count": len(set(left_index).union(right_index)),
        "selectivity": selectivity,
        "max_pairs_per_key": max_pairs_per_key,
        "many_to_many_key_count": many_to_many,
        "one_to_many_key_count": one_to_many,
        "many_to_one_key_count": many_to_one,
    }


def _candidate_score(metrics: Mapping[str, Any], key_specs: Sequence[Mapping[str, Any]]) -> float:
    coverage = (float(metrics["left_match_coverage"]) + float(metrics["right_match_coverage"])) / 2
    completeness = (float(metrics["left_key_completeness"]) + float(metrics["right_key_completeness"])) / 2
    selectivity = float(metrics["selectivity"])
    key_count = len(key_specs)
    contextual_richness = min(1.0, key_count / 3.0)
    has_anchor = any(spec["canonical_name"] in _STRONG_ANCHORS for spec in key_specs)
    anchor_score = 1.0 if has_anchor else 0.0
    # Extra weight on selectivity makes a composite entity+time key rank above
    # a broad entity-only key that creates a cartesian many-to-many join.
    score = (
        0.32 * coverage
        + 0.38 * selectivity
        + 0.12 * completeness
        + 0.12 * contextual_richness
        + 0.06 * anchor_score
    )
    return round(min(max(score, 0.0), 1.0), 6)


def _safety_for_plan(metrics: Mapping[str, Any], key_specs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    anchor_names = [str(spec["canonical_name"]) for spec in key_specs if spec["canonical_name"] in _STRONG_ANCHORS]
    has_anchor = bool(anchor_names)
    many_to_many = int(metrics["many_to_many_key_count"])
    warnings: List[str] = []
    if not has_anchor:
        warnings.append("No strong entity or transaction identifier is present; do not auto-join this plan.")
    if many_to_many:
        warnings.append("%d key value(s) produce many-to-many matches; review duplicate records before relying on totals." % many_to_many)
    if metrics["one_to_many_key_count"] or metrics["many_to_one_key_count"]:
        warnings.append("The join contains one-to-many records; aggregate only with a metric-aware rule to avoid double counting.")
    if not metrics["matched_pair_count"]:
        warnings.append("This plan has no matching records.")
    safe = has_anchor and not many_to_many and bool(metrics["matched_pair_count"])
    return {
        "safe_for_auto_preview": safe,
        "confirmation_required": True,
        "strong_anchor_fields": anchor_names,
        "warnings": warnings,
    }


def _candidate_plan(
    left: _EvidenceTable,
    right: _EvidenceTable,
    key_specs: Sequence[Mapping[str, Any]],
    value_aliases: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    relevant_aliases: Dict[str, Dict[str, Any]] = {}
    for key in key_specs:
        canonical_name = str(key["canonical_name"])
        aliases = (value_aliases or {}).get(canonical_name)
        if aliases is None:
            continue
        if not isinstance(aliases, Mapping):
            raise ValueError("value_aliases must map each field to a key/value mapping")
        relevant_aliases[canonical_name] = dict(aliases)
    metrics = _join_metrics(left, right, key_specs, relevant_aliases)
    safety = _safety_for_plan(metrics, key_specs)
    plan = {
        "plan_id": _plan_id(left, right, key_specs),
        "left": left.ref,
        "right": right.ref,
        "keys": [dict(spec) for spec in key_specs],
        "strategy": "time_bucket" if any(spec["strategy"] == "time_bucket" for spec in key_specs) else "exact",
        "score": _candidate_score(metrics, key_specs),
        "metrics": _public_join_metrics(metrics),
        "safety": safety,
        "approval_state": "proposed",
        "explanation": (
            "Proposed deterministic join. Confirm the selected keys before treating its evidence as an operational conclusion."
        ),
    }
    if relevant_aliases:
        # These mappings are supplied by an approved customer vocabulary or a
        # deliberate manual plan. They are recorded in the plan so every match
        # remains reproducible; no fuzzy/entity-model inference is involved.
        plan["value_aliases"] = relevant_aliases
    return plan


def _public_join_metrics(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    keys = (
        "matched_pair_count",
        "matched_left_record_count",
        "matched_right_record_count",
        "left_keyed_record_count",
        "right_keyed_record_count",
        "left_key_completeness",
        "right_key_completeness",
        "left_match_coverage",
        "right_match_coverage",
        "key_overlap_count",
        "key_union_count",
        "selectivity",
        "max_pairs_per_key",
        "many_to_many_key_count",
        "one_to_many_key_count",
        "many_to_one_key_count",
    )
    result = {name: metrics[name] for name in keys}
    for name in (
        "left_key_completeness",
        "right_key_completeness",
        "left_match_coverage",
        "right_match_coverage",
        "selectivity",
    ):
        result[name] = round(float(result[name]), 6)
    return result


def _candidate_key_name_sets(shared_names: Sequence[str], include_weak_keys: bool) -> List[Tuple[str, ...]]:
    strong = [name for name in shared_names if name in _STRONG_ANCHORS]
    context = [name for name in shared_names if name in _CONTEXT_KEYS]
    names: List[Tuple[str, ...]] = []
    if strong:
        for anchor in strong:
            names.append((anchor,))
            for count in range(1, min(len(context), _MAX_COMPOSITE_CONTEXT_KEYS) + 1):
                for extra in combinations(context, count):
                    names.append((anchor,) + extra)
        # Transaction + asset is often a more precise safety anchor.
        for count in range(2, min(len(strong), 2) + 1):
            for anchor_combo in combinations(strong, count):
                names.append(anchor_combo)
                for extra in combinations(context, min(len(context), _MAX_COMPOSITE_CONTEXT_KEYS)):
                    if extra:
                        names.append(anchor_combo + extra)
    elif include_weak_keys:
        # Weak plans are shown for a user to review, never selected as safe
        # automatic previews.  Date+shift-only joins are especially risky.
        for count in range(1, min(len(context), _MAX_COMPOSITE_CONTEXT_KEYS) + 1):
            names.extend(combinations(context, count))

    unique: List[Tuple[str, ...]] = []
    seen = set()
    for nameset in names:
        ordered = tuple(sorted(nameset, key=_key_sort_key))
        if ordered not in seen:
            seen.add(ordered)
            unique.append(ordered)
    return unique


def _key_sort_key(name: str) -> Tuple[int, str]:
    priority = {
        "asset_id": 0,
        "trailer_id": 0,
        "work_order_id": 0,
        "order_id": 0,
        "purchase_order_id": 0,
        "sales_order_id": 0,
        "invoice_id": 0,
        "lot_id": 0,
        "batch_id": 0,
        "shipment_id": 0,
        "tracking_id": 0,
        "facility": 1,
        "line_id": 2,
        "event_time": 3,
        "shift": 4,
    }
    return priority.get(name, 10), name


def _profile_join_candidates_for_tables(
    tables: Sequence[_EvidenceTable],
    *,
    time_bucket_minutes: int = 60,
    include_weak_keys: bool = False,
    max_candidates_per_pair: int = 40,
    value_aliases: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if time_bucket_minutes <= 0:
        raise ValueError("time_bucket_minutes must be greater than zero")
    candidates: List[Dict[str, Any]] = []
    for left, right in combinations(tables, 2):
        left_columns = _best_columns_by_canonical(left)
        right_columns = _best_columns_by_canonical(right)
        shared_names = sorted(
            name for name in set(left_columns).intersection(right_columns)
            if _type_compatible(left_columns[name], right_columns[name])
        )
        for nameset in _candidate_key_name_sets(shared_names, include_weak_keys):
            exact_specs = [
                _field_spec(name, left_columns[name], right_columns[name], "exact", None)
                for name in nameset
            ]
            candidates.append(_candidate_plan(left, right, exact_specs, value_aliases))
            if _TEMPORAL_KEY in nameset:
                bucket_specs = [
                    _field_spec(name, left_columns[name], right_columns[name], "time_bucket", time_bucket_minutes)
                    for name in nameset
                ]
                # When one sheet carries a date and the other a timestamp, a
                # calendar-day bucket is the only lossless default.
                for spec in bucket_specs:
                    if spec["canonical_name"] == _TEMPORAL_KEY:
                        spec["date_granularity"] = (
                            left_columns[_TEMPORAL_KEY].logical_type == "date"
                            or right_columns[_TEMPORAL_KEY].logical_type == "date"
                        )
                candidates.append(_candidate_plan(left, right, bucket_specs, value_aliases))

    candidates.sort(
        key=lambda item: (
            not bool(item["safety"]["safe_for_auto_preview"]),
            -float(item["score"]),
            -int(item["metrics"]["matched_pair_count"]),
            item["plan_id"],
        )
    )
    return candidates[: max(0, max_candidates_per_pair) * max(1, len(tables))]


def profile_join_candidates(
    sources: Sequence[Mapping[str, Any]],
    *,
    time_bucket_minutes: int = 60,
    include_weak_keys: bool = False,
    max_candidates_per_pair: int = 40,
    value_aliases: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Propose ranked, deterministic join plans across all source tables.

    Plans require a strong entity/transaction anchor by default.  Set
    ``include_weak_keys`` only to surface (not auto-approve) date/shift-based
    plans for a human reviewer.
    """
    return _profile_join_candidates_for_tables(
        _normalize_sources(sources),
        time_bucket_minutes=time_bucket_minutes,
        include_weak_keys=include_weak_keys,
        max_candidates_per_pair=max_candidates_per_pair,
        value_aliases=value_aliases,
    )


def _find_table(tables: Sequence[_EvidenceTable], ref: Mapping[str, Any]) -> _EvidenceTable:
    source_id = str(ref.get("source_id") or "")
    source_key = str(ref.get("source_key") or "")
    table_name = str(ref.get("table_name") or "")
    table_key = str(ref.get("table_key") or "")
    matches = [
        table for table in tables
        if (not source_id or table.source_id == source_id)
        and (not source_key or table.source_key == source_key)
        and (not table_name or table.table_name == table_name)
        and (not table_key or table.table_key == table_key)
    ]
    if len(matches) != 1:
        raise ValueError("Join plan must identify exactly one source table per side")
    return matches[0]


def _is_rejected_plan(plan: Optional[Mapping[str, Any]]) -> bool:
    """Return whether a caller explicitly rejected a proposed table pair."""

    return bool(plan) and str(plan.get("approval_state") or "").casefold() == "rejected"


def _resolve_join_plan(
    tables: Sequence[_EvidenceTable],
    join_plan: Optional[Mapping[str, Any]],
    time_bucket_minutes: int,
    include_weak_keys: bool,
    value_aliases: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[_EvidenceTable], Optional[_EvidenceTable], str]:
    if _is_rejected_plan(join_plan):
        # An explicit rejection must never fall through to auto-selection. This
        # makes a user-rejected pair a real decision rather than a cosmetic UI
        # state that silently reappears in the next evidence preview.
        return None, None, None, "rejected"
    if join_plan is None:
        candidates = _profile_join_candidates_for_tables(
            tables,
            time_bucket_minutes=time_bucket_minutes,
            include_weak_keys=include_weak_keys,
            value_aliases=value_aliases,
        )
        selected = next(
            (candidate for candidate in candidates if candidate["safety"]["safe_for_auto_preview"]),
            None,
        )
        if selected is None:
            return None, None, None, "none"
        return selected, _find_table(tables, selected["left"]), _find_table(tables, selected["right"]), "auto_preview"

    selected = dict(join_plan)
    if value_aliases:
        merged_aliases: Dict[str, Dict[str, Any]] = {}
        for field, aliases in value_aliases.items():
            if not isinstance(aliases, Mapping):
                raise ValueError("value_aliases must map each field to a key/value mapping")
            merged_aliases[str(field)] = dict(aliases)
        for field, aliases in (selected.get("value_aliases") or {}).items():
            if not isinstance(aliases, Mapping):
                raise ValueError("join plan value_aliases must map each field to a key/value mapping")
            merged_aliases.setdefault(str(field), {}).update(dict(aliases))
        selected["value_aliases"] = merged_aliases
    left = _find_table(tables, selected.get("left") or {})
    right = _find_table(tables, selected.get("right") or {})
    raw_keys = selected.get("keys") or []
    if not raw_keys:
        raise ValueError("Join plan must include at least one key")
    left_columns = {column.name: column for column in left.columns}
    right_columns = {column.name: column for column in right.columns}
    keys: List[Dict[str, Any]] = []
    for raw_key in raw_keys:
        key = dict(raw_key)
        canonical_name = str(key.get("canonical_name") or key.get("name") or "")
        left_column = str(key.get("left_column") or "")
        right_column = str(key.get("right_column") or "")
        if not canonical_name or left_column not in left_columns or right_column not in right_columns:
            raise ValueError("Join plan key columns must exist in their selected tables")
        strategy = str(key.get("strategy") or "exact")
        if strategy not in {"exact", "time_bucket"}:
            raise ValueError("Join strategy must be 'exact' or 'time_bucket'")
        if strategy == "time_bucket" and canonical_name != _TEMPORAL_KEY:
            raise ValueError("time_bucket is only valid for temporal fields")
        key.update({
            "canonical_name": canonical_name,
            "left_column": left_column,
            "right_column": right_column,
            "strategy": strategy,
            "time_bucket_minutes": int(key.get("time_bucket_minutes") or time_bucket_minutes)
            if strategy == "time_bucket" else None,
            "semantic_type": key.get("semantic_type") or _semantic_type(canonical_name),
        })
        keys.append(key)
    selected["keys"] = keys
    # A caller can edit a candidate's keys/strategy while retaining its old
    # plan_id. The provenance ID must describe the *resolved* configuration,
    # never a stale proposal.
    selected["plan_id"] = _plan_id(left, right, keys)
    selected.setdefault("left", left.ref)
    selected.setdefault("right", right.ref)
    selected.setdefault("approval_state", "confirmed")
    return selected, left, right, "confirmed"


def _flatten_fields(record: _EvidenceRecord, side: str) -> Dict[str, Any]:
    return {"%s.%s" % (side, _canonical_column_name(name)): _json_safe(value) for name, value in record.values.items()}


def _join_key_display(key_specs: Sequence[Mapping[str, Any]], key: Tuple[str, ...]) -> Dict[str, str]:
    return {str(spec["canonical_name"]): value for spec, value in zip(key_specs, key)}


def _evidence_id(plan_id: str, left: Optional[_EvidenceRecord], right: Optional[_EvidenceRecord]) -> str:
    token = "%s|%s|%s" % (
        plan_id,
        left.lineage.row_id if left is not None else "",
        right.lineage.row_id if right is not None else "",
    )
    return "evidence-%s" % sha256(token.encode("utf-8")).hexdigest()[:16]


def _alias_fingerprint(aliases_by_field: Mapping[str, Any]) -> str:
    """Fingerprint approved deterministic aliases as part of evidence provenance."""
    if not aliases_by_field:
        return ""
    encoded = json.dumps(_json_safe(aliases_by_field), sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()[:10]


def _make_evidence_row(
    plan_id: str,
    key_specs: Sequence[Mapping[str, Any]],
    key: Optional[Tuple[str, ...]],
    status: str,
    left: Optional[_EvidenceRecord],
    right: Optional[_EvidenceRecord],
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    lineages: List[Dict[str, Any]] = []
    source_rows: List[Dict[str, Any]] = []
    if left is not None:
        fields.update(_flatten_fields(left, "left"))
        lineages.append(left.lineage.as_dict())
        source_rows.append({
            "side": "left",
            "lineage": left.lineage.as_dict(),
            "values": {str(name): _json_safe(value) for name, value in left.values.items()},
        })
    if right is not None:
        fields.update(_flatten_fields(right, "right"))
        lineages.append(right.lineage.as_dict())
        source_rows.append({
            "side": "right",
            "lineage": right.lineage.as_dict(),
            "values": {str(name): _json_safe(value) for name, value in right.values.items()},
        })
    return {
        "evidence_id": _evidence_id(plan_id, left, right),
        "match_status": status,
        "join_key": _join_key_display(key_specs, key) if key is not None else None,
        "lineage": lineages,
        "source_rows": source_rows,
        "fields": fields,
    }


def _quality_metrics(
    left: _EvidenceTable,
    right: _EvidenceTable,
    metrics: Mapping[str, Any],
    key_specs: Sequence[Mapping[str, Any]],
    safety: Mapping[str, Any],
) -> Dict[str, Any]:
    coverage = (float(metrics["left_match_coverage"]) + float(metrics["right_match_coverage"])) / 2
    completeness = (float(metrics["left_key_completeness"]) + float(metrics["right_key_completeness"])) / 2
    selectivity = float(metrics["selectivity"])
    anchor_quality = 1.0 if safety.get("strong_anchor_fields") else 0.0
    # This is evidence quality, never causal confidence.  It rewards complete,
    # selective, anchored joins and is deterministic for the same source rows.
    score = round(min(1.0, max(0.0, 0.40 * coverage + 0.30 * selectivity + 0.20 * completeness + 0.10 * anchor_quality)), 6)
    if score >= 0.85 and not metrics["many_to_many_key_count"]:
        label = "high"
    elif score >= 0.60:
        label = "moderate"
    else:
        label = "low"
    warnings = list(safety.get("warnings") or [])
    if coverage < 0.5:
        warnings.append("Less than half of at least one table matched; inspect aliases, dates, and source completeness.")
    if metrics["left_key_completeness"] < 0.9 or metrics["right_key_completeness"] < 0.9:
        warnings.append("Some rows lack one or more join keys and remain unmatched.")
    return {
        "left_table_row_count": len(left.records),
        "right_table_row_count": len(right.records),
        **_public_join_metrics(metrics),
        "evidence_quality_score": score,
        "evidence_quality_label": label,
        "review_required": bool(
            not safety.get("safe_for_auto_preview")
            or metrics["many_to_many_key_count"]
            or metrics["one_to_many_key_count"]
            or metrics["many_to_one_key_count"]
            or score < 0.60
        ),
        "interpretation": (
            "This score measures row-link quality only. Matched records are evidence of co-occurrence, not proof of causation."
        ),
        "warnings": list(dict.fromkeys(warnings)),
    }


def build_evidence_table(
    sources: Sequence[Mapping[str, Any]],
    *,
    join_plan: Optional[Mapping[str, Any]] = None,
    time_bucket_minutes: int = 60,
    include_weak_keys: bool = False,
    max_match_pairs: int = _DEFAULT_MAX_MATCH_PAIRS,
    value_aliases: Optional[Mapping[str, Mapping[str, Any]]] = None,
    # Private graph-execution hooks.  ``build_evidence_graph`` has already
    # normalized/profiled its full table set and owns the graph-wide candidate
    # catalog, so an edge must not redo that O(table-pairs) work only for the
    # caller to discard it.  The public/default path deliberately retains the
    # complete standalone table-preview response.
    _precomputed_tables: Optional[Sequence[_EvidenceTable]] = None,
    _include_candidate_join_plans: bool = True,
    _include_source_profile: bool = True,
) -> Dict[str, Any]:
    """Create a lineage-preserving common evidence table for one join plan.

    With no plan, the top safe candidate is executed as a read-only preview and
    marked as requiring confirmation.  Pass a plan returned by
    :func:`profile_join_candidates` after the user confirms it to make the
    chosen keys explicit.  Unmatched rows are always retained.
    """
    if time_bucket_minutes <= 0:
        raise ValueError("time_bucket_minutes must be greater than zero")
    if max_match_pairs <= 0:
        raise ValueError("max_match_pairs must be greater than zero")
    tables = list(_precomputed_tables) if _precomputed_tables is not None else _normalize_sources(sources)
    source_profile = _profile_evidence_tables(tables) if _include_source_profile else None
    selected, left, right, selection_mode = _resolve_join_plan(
        tables, join_plan, time_bucket_minutes, include_weak_keys, value_aliases
    )
    if selected is None or left is None or right is None:
        rejected = selection_mode == "rejected"
        result = {
            "join_plan": None,
            "selection_mode": selection_mode,
            "evidence_rows": [],
            "matched_rows": [],
            "unmatched_left_rows": [],
            "unmatched_right_rows": [],
            "quality": {
                "evidence_quality_score": 0.0,
                "evidence_quality_label": "low",
                "review_required": True,
                "interpretation": (
                    "The supplied join plan was rejected; no records were correlated."
                    if rejected else
                    "No safe deterministic join plan was found; no records were correlated."
                ),
                "warnings": (
                    ["The supplied join plan is rejected. Select or edit a different plan before correlating records."]
                    if rejected else
                    ["Add a shared entity/transaction ID or explicitly review a weak candidate."]
                ),
            },
        }
        if _include_candidate_join_plans:
            result["candidate_join_plans"] = _profile_join_candidates_for_tables(
                tables,
                time_bucket_minutes=time_bucket_minutes,
                include_weak_keys=include_weak_keys,
                value_aliases=value_aliases,
            )
        if _include_source_profile:
            result["source_profile"] = source_profile
        return result

    aliases_by_field = selected.get("value_aliases") or {}
    alias_fingerprint = _alias_fingerprint(aliases_by_field)
    if alias_fingerprint:
        selected["plan_id"] = "%s-a%s" % (selected["plan_id"], alias_fingerprint)
    metrics = _join_metrics(left, right, selected["keys"], aliases_by_field)
    safety = _safety_for_plan(metrics, selected["keys"])
    selected["metrics"] = _public_join_metrics(metrics)
    selected["score"] = _candidate_score(metrics, selected["keys"])
    selected["safety"] = safety
    selected["strategy"] = "time_bucket" if any(key["strategy"] == "time_bucket" for key in selected["keys"]) else "exact"
    if selection_mode == "auto_preview":
        selected["approval_state"] = "proposed"

    matched_rows: List[Dict[str, Any]] = []
    unmatched_left_rows: List[Dict[str, Any]] = []
    unmatched_right_rows: List[Dict[str, Any]] = []
    matched_left_ids = set()
    matched_right_ids = set()
    emitted_pairs = 0
    truncated = False
    for key in metrics["shared_keys"]:
        for left_record in metrics["left_index"][key]:
            for right_record in metrics["right_index"][key]:
                if emitted_pairs >= max_match_pairs:
                    truncated = True
                    break
                matched_rows.append(_make_evidence_row(
                    selected["plan_id"], selected["keys"], key, "matched", left_record, right_record
                ))
                matched_left_ids.add(left_record.lineage.row_id)
                matched_right_ids.add(right_record.lineage.row_id)
                emitted_pairs += 1
            if truncated:
                break
        if truncated:
            break

    # A cap should not pretend that unprocessed matches are unmatched. Keep
    # unmatched lists accurate only when every planned pair was emitted.
    if not truncated:
        for record in left.records:
            if record.lineage.row_id not in matched_left_ids:
                unmatched_left_rows.append(_make_evidence_row(
                    selected["plan_id"], selected["keys"], None, "unmatched_left", record, None
                ))
        for record in right.records:
            if record.lineage.row_id not in matched_right_ids:
                unmatched_right_rows.append(_make_evidence_row(
                    selected["plan_id"], selected["keys"], None, "unmatched_right", None, record
                ))

    quality = _quality_metrics(left, right, metrics, selected["keys"], safety)
    if truncated:
        quality["review_required"] = True
        quality["warnings"].append(
            "Join preview stopped at %d matched pairs; narrow or refine the join plan before using totals." % max_match_pairs
        )
    evidence_rows = matched_rows + unmatched_left_rows + unmatched_right_rows
    result = {
        "join_plan": selected,
        "selection_mode": selection_mode,
        "evidence_rows": evidence_rows,
        "matched_rows": matched_rows,
        "unmatched_left_rows": unmatched_left_rows,
        "unmatched_right_rows": unmatched_right_rows,
        "truncated": truncated,
        "quality": quality,
    }
    if _include_candidate_join_plans:
        result["candidate_join_plans"] = _profile_join_candidates_for_tables(
            tables,
            time_bucket_minutes=time_bucket_minutes,
            include_weak_keys=include_weak_keys,
            value_aliases=value_aliases,
        )
    if _include_source_profile:
        result["source_profile"] = source_profile
    return result


def _plan_table_pair_key(plan: Mapping[str, Any]) -> Tuple[Tuple[str, str], Tuple[str, str]]:
    """Return an order-independent identity for the two tables in a plan."""
    sides: List[Tuple[str, str]] = []
    for side_name in ("left", "right"):
        side = plan.get(side_name) or {}
        sides.append((
            str(side.get("source_key") or side.get("source_id") or ""),
            str(side.get("table_key") or side.get("table_name") or ""),
        ))
    return tuple(sorted(sides))  # type: ignore[return-value]


def build_evidence_graph(
    sources: Sequence[Mapping[str, Any]],
    *,
    join_plans: Optional[Sequence[Mapping[str, Any]]] = None,
    time_bucket_minutes: int = 60,
    include_weak_keys: bool = False,
    max_match_pairs: int = _DEFAULT_MAX_MATCH_PAIRS,
    max_evidence_sets: int = 25,
    value_aliases: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a bounded, pairwise common-evidence graph across many sources.

    A common table is intrinsically a relationship between two source tables.
    This helper therefore preserves that grain rather than flattening several
    potentially one-to-many joins into a misleading mega-row.  It selects one
    safe proposed plan per table pair when no plans are supplied, and emits a
    separate lineage-preserving evidence set for each edge.  The total matched
    pair budget is shared across edges.

    Passing ``join_plans`` represents an explicit, user-confirmed graph.  The
    no-plan path remains a read-only preview whose plans are marked proposed.
    """
    if max_match_pairs <= 0:
        raise ValueError("max_match_pairs must be greater than zero")
    if max_evidence_sets <= 0:
        raise ValueError("max_evidence_sets must be greater than zero")

    tables = _normalize_sources(sources)
    source_profile = _profile_evidence_tables(tables)
    candidates = _profile_join_candidates_for_tables(
        tables,
        time_bucket_minutes=time_bucket_minutes,
        include_weak_keys=include_weak_keys,
        value_aliases=value_aliases,
    )

    # ``None`` means no user decision has been supplied, while an explicit
    # empty list means the reviewer deliberately selected no relationships.
    # Preserve that distinction so rejected plans cannot fall back to the
    # automatic graph on the next request.
    explicit_requested = join_plans is not None
    supplied_plans = [dict(plan) for plan in (join_plans or [])]
    eligible_pair_keys = set()
    for candidate in candidates:
        if not candidate.get("safety", {}).get("safe_for_auto_preview"):
            continue
        eligible_pair_keys.add(_plan_table_pair_key(candidate))

    rejected_pair_keys = {
        _plan_table_pair_key(plan)
        for plan in supplied_plans
        if _is_rejected_plan(plan)
    }
    rejected_plan_count = sum(1 for plan in supplied_plans if _is_rejected_plan(plan))
    duplicate_plan_count = 0
    limit_skipped_plan_count = 0
    if explicit_requested:
        selected_plans: List[Dict[str, Any]] = []
        selected_pairs = set()
        for plan in supplied_plans:
            if _is_rejected_plan(plan):
                continue
            pair_key = _plan_table_pair_key(plan)
            # A reject takes precedence over a competing selection for the
            # same pair. The caller must submit a later explicit review rather
            # than accidentally materialising a relationship it just rejected.
            if pair_key in rejected_pair_keys:
                continue
            if pair_key in selected_pairs:
                duplicate_plan_count += 1
                continue
            if len(selected_plans) >= max_evidence_sets:
                limit_skipped_plan_count += 1
                continue
            selected_pairs.add(pair_key)
            selected_plans.append(plan)
        selection_mode = "confirmed_graph"
    else:
        selected_plans: List[Dict[str, Any]] = []
        selected_pairs = set()
        for candidate in candidates:
            if not candidate.get("safety", {}).get("safe_for_auto_preview"):
                continue
            pair_key = _plan_table_pair_key(candidate)
            if pair_key in selected_pairs:
                continue
            selected_pairs.add(pair_key)
            selected_plans.append(dict(candidate))
            if len(selected_plans) >= max_evidence_sets:
                break
        selection_mode = "auto_preview_graph"

    relationship_scope_truncated = (
        limit_skipped_plan_count > 0
        if explicit_requested
        else len(selected_plans) < len(eligible_pair_keys)
    )
    if explicit_requested:
        if not selected_plans and rejected_plan_count:
            scope_note = "All supplied join plans were rejected; no records were correlated."
        elif relationship_scope_truncated:
            scope_note = (
                "Only %d explicit join plans fit the %d-relationship limit; review the omitted plans before treating this as a complete operational scope."
                % (len(selected_plans), max_evidence_sets)
            )
        else:
            scope_note = "The graph contains %d explicitly confirmed table pair(s)." % len(selected_plans)
    else:
        scope_note = (
            "Only %d of %d eligible table pairs were materialized. Narrow the selected tables or explicitly confirm the needed joins before treating this as a complete operational scope."
            % (len(selected_plans), len(eligible_pair_keys))
            if relationship_scope_truncated else
            "Every eligible safe table pair in the selected scope was materialized."
        )
    graph_scope = {
        "table_count": len(tables),
        "eligible_safe_pair_count": len(eligible_pair_keys),
        "selected_pair_count": len(selected_plans),
        "relationship_limit": max_evidence_sets,
        "partial_graph": relationship_scope_truncated,
        "explicit_plan_selection": explicit_requested,
        "supplied_plan_count": len(supplied_plans),
        "rejected_plan_count": rejected_plan_count,
        "duplicate_plan_count": duplicate_plan_count,
        "limit_skipped_plan_count": limit_skipped_plan_count,
        "scope_note": scope_note,
    }

    if not selected_plans:
        return {
            "selection_mode": selection_mode,
            "candidate_join_plans": candidates,
            "evidence_sets": [],
            "source_profile": source_profile,
            "relationship_count": 0,
            "graph_scope": graph_scope,
            "matched_pair_count": 0,
            "review_required": True,
            "quality": {
                "evidence_quality_score": 0.0,
                "evidence_quality_label": "low",
                "review_required": True,
                "interpretation": (
                    "No confirmed join plan remains, so no records were correlated."
                    if explicit_requested else
                    "No safe deterministic join graph was found; no records were correlated."
                ),
                "warnings": (
                    [scope_note]
                    if explicit_requested else
                    ["Add a shared entity/transaction ID or explicitly review a weak candidate."]
                ),
            },
        }

    # Keep a many-source preview bounded as a whole. Each edge reports whether
    # its local join reached its allocation so a UI never mistakes a partial
    # graph for complete aggregate evidence.
    pairs_per_set = max(1, max_match_pairs // len(selected_plans))
    evidence_sets: List[Dict[str, Any]] = []
    for plan in selected_plans:
        if explicit_requested:
            plan["approval_state"] = "confirmed"
        else:
            plan["approval_state"] = "proposed"
        evidence = build_evidence_table(
            sources,
            join_plan=plan,
            time_bucket_minutes=time_bucket_minutes,
            include_weak_keys=include_weak_keys,
            max_match_pairs=pairs_per_set,
            value_aliases=value_aliases,
            _precomputed_tables=tables,
            _include_candidate_join_plans=False,
            _include_source_profile=False,
        )
        # The graph owns the complete candidate catalog and source profile.
        # The private execution path above deliberately omits both from each
        # edge, avoiding repeated all-pairs profiling that the graph would
        # otherwise discard immediately.
        # build_evidence_table intentionally calls an explicitly supplied plan
        # "confirmed". In the auto graph path it is only a proposed preview.
        evidence["selection_mode"] = (
            "confirmed" if explicit_requested else "auto_preview"
        )
        if evidence.get("join_plan"):
            evidence["join_plan"]["approval_state"] = (
                "confirmed" if explicit_requested else "proposed"
            )
        evidence_sets.append(evidence)

    edge_scores = [
        float((edge.get("quality") or {}).get("evidence_quality_score") or 0.0)
        for edge in evidence_sets
    ]
    matched_pair_count = sum(len(edge.get("matched_rows") or []) for edge in evidence_sets)
    review_required = relationship_scope_truncated or any(
        bool((edge.get("quality") or {}).get("review_required"))
        or bool(edge.get("truncated"))
        for edge in evidence_sets
    )
    warnings: List[str] = []
    for edge in evidence_sets:
        warnings.extend((edge.get("quality") or {}).get("warnings") or [])
    if relationship_scope_truncated:
        warnings.append(graph_scope["scope_note"])
    return {
        "selection_mode": selection_mode,
        "candidate_join_plans": candidates,
        "evidence_sets": evidence_sets,
        "source_profile": source_profile,
        "relationship_count": len(evidence_sets),
        "graph_scope": graph_scope,
        "matched_pair_count": matched_pair_count,
        "review_required": review_required,
        "truncated": any(bool(edge.get("truncated")) for edge in evidence_sets),
        "quality": {
            "evidence_quality_score": round(sum(edge_scores) / len(edge_scores), 6),
            "evidence_quality_label": (
                "high" if edge_scores and min(edge_scores) >= 0.85
                else "moderate" if edge_scores and sum(edge_scores) / len(edge_scores) >= 0.60
                else "low"
            ),
            "review_required": review_required,
            "interpretation": (
                "Graph quality is the average row-link quality across pairwise evidence sets. "
                "It is not causal confidence and must not be used to infer causation."
            ),
            "warnings": list(dict.fromkeys(warnings)),
        },
    }


__all__ = [
    "EvidenceLineage",
    "build_entity_rollups",
    "build_evidence_graph",
    "build_evidence_table",
    "infer_typed_schema",
    "profile_evidence_sources",
    "profile_join_candidates",
]
