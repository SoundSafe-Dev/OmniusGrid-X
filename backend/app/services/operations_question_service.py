"""Deterministic, evidence-backed answers to operations-lead questions.

This service is intentionally the last step of an evidence workflow.  It does
not call an LLM, infer a hidden join, or turn an observational association into
a root-cause claim.  Instead, it translates a common evidence table and its
bounded analytics into a small, structured briefing an operations lead can
review.

The public entry point accepts either a direct evidence-table result from
``build_evidence_table`` or a multi-table graph result from
``build_evidence_graph``.  It also accepts analytics already calculated by the
caller (at the top level or on graph edges), so answering a question never has
to silently launch an expensive second analysis.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.services.operational_analytics import causation_guardrail


QUESTION_OVERVIEW = "operations_overview"
QUESTION_DOWNTIME = "downtime_drivers"
QUESTION_CHANGED = "what_changed"
QUESTION_PRIORITY = "prioritization"
QUESTION_QUALITY = "quality_reconciliation"
QUESTION_MAINTENANCE = "maintenance_risk"
QUESTION_PERFORMANCE = "performance_and_bottlenecks"
QUESTION_SAFETY = "safety_compliance"
QUESTION_SUPPLY = "supply_and_logistics"
QUESTION_WORKFORCE = "workforce_readiness"
QUESTION_CHECKLIST = "next_shift_checklist"
QUESTION_UNSUPPORTED = "needs_clarification"

_MAX_FINDINGS = 5
_MAX_CITATIONS = 4
_HISTORICAL_AFTER_DAYS = 14


def _normalise(value: Any) -> str:
    """Return a conservative token form for deterministic field matching."""
    text = str(value or "").casefold()
    return "_".join(re.findall(r"[a-z0-9]+", text))


def _terminal_field(field: Any) -> str:
    """Drop evidence-engine side prefixes such as ``left.downtime_minutes``."""
    return _normalise(str(field).rsplit(".", 1)[-1])


def _display_field(field: Any) -> str:
    """Keep source-qualified evidence keys readable in an operations answer."""

    return str(field).rsplit(".", 1)[-1] or str(field)


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    return any(term in text for term in terms)


def _question_terms(question: str) -> Tuple[str, List[str]]:
    normalized = _normalise(question)
    tokens = [token for token in normalized.split("_") if token]
    return normalized, tokens


def classify_operations_question(question: Any) -> Dict[str, Any]:
    """Classify common operations questions without an LLM or fuzzy matching.

    The explicit phrase catalog deliberately recognises several natural styles
    (for example, "what's hurting us?" and "why are we losing time?") while
    returning ``needs_clarification`` for a question outside operational scope.
    The classification is part of the returned answer so a UI can let a user
    correct it before the service is used to drive a workflow.
    """
    text = str(question or "").strip()
    normalized, tokens = _question_terms(text)
    if not normalized:
        return {
            "intent": QUESTION_UNSUPPORTED,
            "confidence": "low",
            "matched_terms": [],
            "reason": "No question was supplied.",
        }

    rules: Sequence[Tuple[str, Tuple[str, ...], str]] = (
        (
            QUESTION_CHECKLIST,
            (
                "next_shift", "nextshift", "shift_checklist", "checklist",
                "what_do_i_check", "what_should_i_check", "what_needs_checked",
                "shift_handoff", "handoff", "what_do_we_inspect",
                "before_next_crew", "before_the_next_crew", "next_crew",
                "before_shift", "shift_start", "crew_starts", "crew_start",
            ),
            "The question asks for a handoff, inspection, or checklist.",
        ),
        (
            QUESTION_QUALITY,
            (
                "quality", "defect", "defects", "scrap", "reject", "rework",
                "yield", "reconcile", "reconciliation", "disagree", "variance",
                "where_are_the_quality_issues",
            ),
            "The question asks about quality signals or reconciliation.",
        ),
        (
            QUESTION_SAFETY,
            (
                "safety", "incident", "incidents", "near_miss", "near_misses",
                "compliance", "osha", "citation", "citations", "hazard", "hazards",
            ),
            "The question asks about safety observations, incidents, or compliance evidence.",
        ),
        (
            QUESTION_SUPPLY,
            (
                "supply", "supplier", "suppliers", "logistics", "material", "materials",
                "inventory", "stockout", "stock_out", "delivery", "deliveries", "carrier",
                "shipment", "shipments", "detention", "backlog", "shortage", "shortages",
            ),
            "The question asks about material flow, inventory, delivery, or logistics evidence.",
        ),
        (
            QUESTION_WORKFORCE,
            (
                "workforce", "staffing", "staff", "labor", "operator", "operators",
                "overtime", "absenteeism", "attendance", "training", "turnover", "headcount",
            ),
            "The question asks about workforce capacity or readiness evidence.",
        ),
        (
            QUESTION_MAINTENANCE,
            (
                "maintenance", "pm", "preventive_maintenance", "health", "vibration",
                "condition", "bearing", "failure_risk", "work_order", "service",
                "repair", "needs_work", "need_work", "machine_needs", "machine_service",
                "machines_likely", "likely_to_need",
            ),
            "The question asks about maintenance or condition risk.",
        ),
        (
            QUESTION_CHANGED,
            (
                "what_changed", "what_has_changed", "change_point", "changed",
                "different", "shifted", "shift_change", "trend_change", "new_pattern",
                "anomaly", "anomalies", "outlier", "outliers", "unusual", "spike",
            ),
            "The question asks for a detected change or trend shift.",
        ),
        (
            QUESTION_DOWNTIME,
            (
                "downtime", "down_time", "why_are_we_losing_time", "losing_time",
                "why_down", "what_is_hurting_us", "what_s_hurting_us", "whats_hurting_us", "drivers",
                "root_cause", "why_is", "stoppage", "unplanned_stop", "line_stop",
                "did_line", "biggest_loss", "biggest_losses", "losses", "stopped", "stop",
            ),
            "The question asks about lost production time or its observed associations.",
        ),
        (
            QUESTION_PRIORITY,
            (
                "prioritize", "priority", "what_needs_attention", "needs_attention",
                "where_should", "which_asset", "which_assets", "which_line", "which_shift",
                "focus_first", "top_risk", "worst_asset", "worst_line", "worst_shift",
                "worry_about", "need_to_worry", "look_at_first", "review_first",
            ),
            "The question asks which operational entity should be reviewed first.",
        ),
        (
            QUESTION_PERFORMANCE,
            (
                "on_plan", "on_target", "behind_plan", "behind_schedule", "ahead_of_plan",
                "performance", "throughput", "bottleneck", "bottlenecks", "constraint",
                "constraints", "capacity", "increase_output", "increase_production", "output",
                "actual_vs_plan", "planned_vs_actual", "hit_target", "meet_target", "oee",
            ),
            "The question asks about output, plan attainment, throughput, or a potential bottleneck.",
        ),
        (
            QUESTION_OVERVIEW,
            (
                "overview", "operations_overview", "operational_overview", "operations_summary",
                "operational_summary", "how_are_operations", "how_is_operations", "status",
                "briefing", "what_is_happening", "how_are_we_doing",
            ),
            "The question asks for a broad operational briefing.",
        ),
    )

    matched: List[str] = []
    for intent, phrases, reason in rules:
        hits = [phrase for phrase in phrases if phrase in normalized]
        if hits:
            # Single common operational words such as "status" are weaker
            # than a complete phrase, but still intentionally deterministic.
            confidence = "high" if any("_" in hit or len(hit) > 7 for hit in hits) else "medium"
            return {
                "intent": intent,
                "confidence": confidence,
                "matched_terms": hits,
                "reason": reason,
            }
        matched.extend(token for token in tokens if token in phrases)

    # A terse but plainly operational request is useful enough to route to an
    # overview rather than pretending that we understood a specialized ask.
    if set(tokens) & {"operations", "operation", "production", "plant", "facility", "shift", "line", "asset", "machine", "equipment"}:
        return {
            "intent": QUESTION_OVERVIEW,
            "confidence": "low",
            "matched_terms": sorted(set(tokens) & {"operations", "operation", "production", "plant", "facility", "shift", "line", "asset", "machine", "equipment"}),
            "reason": "A general operational term was present; returning a conservative overview.",
        }
    return {
        "intent": QUESTION_UNSUPPORTED,
        "confidence": "low",
        "matched_terms": [],
        "reason": "The question did not match a supported evidence-backed operations intent.",
    }


def suggested_operations_questions() -> List[Dict[str, str]]:
    """Return example questions that map to the deterministic intent catalog."""
    return [
        {"intent": QUESTION_OVERVIEW, "question": "Give me an overview of operations."},
        {"intent": QUESTION_DOWNTIME, "question": "What's hurting us and why are we losing time?"},
        {"intent": QUESTION_CHANGED, "question": "What changed in the operation?"},
        {"intent": QUESTION_PRIORITY, "question": "What needs attention first: asset, line, or shift?"},
        {"intent": QUESTION_QUALITY, "question": "Where are the quality issues or reconciliation gaps?"},
        {"intent": QUESTION_MAINTENANCE, "question": "Which assets show maintenance risk?"},
        {"intent": QUESTION_PERFORMANCE, "question": "Are we on plan, and where is the bottleneck?"},
        {"intent": QUESTION_SAFETY, "question": "Are there safety or compliance issues to review?"},
        {"intent": QUESTION_SUPPLY, "question": "Are materials, inventory, or deliveries constraining operations?"},
        {"intent": QUESTION_WORKFORCE, "question": "Is staffing, overtime, or absenteeism a shift-readiness concern?"},
        {"intent": QUESTION_CHECKLIST, "question": "What do I check next shift?"},
    ]


def _coerce_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        multiplier = 0.01 if text.endswith("%") else 1.0
        if text.endswith("%"):
            text = text[:-1].strip()
        try:
            numeric = float(text) * multiplier
        except ValueError:
            return None
        return numeric if math.isfinite(numeric) else None
    return None


def _as_rows(value: Any) -> List[Mapping[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, Mapping)]
    if isinstance(value, tuple):
        return [row for row in value if isinstance(row, Mapping)]
    return []


def _evidence_rows(evidence_result: Any) -> List[Mapping[str, Any]]:
    """Extract rows from a direct result, graph result, or a plain row list."""
    if isinstance(evidence_result, (list, tuple)):
        return _as_rows(evidence_result)
    if not isinstance(evidence_result, Mapping):
        return []
    rows = _as_rows(evidence_result.get("evidence_rows"))
    if rows:
        return rows
    extracted: List[Mapping[str, Any]] = []
    for edge in _as_rows(evidence_result.get("evidence_sets")):
        extracted.extend(_as_rows(edge.get("evidence_rows") or edge.get("matched_rows")))
    return extracted


def _source_observation_key(lineage: Mapping[str, Any], fallback: int) -> Tuple[str, str, str]:
    """Build a stable identity for one raw source row across graph edges."""

    source_id = str(lineage.get("source_id") or "source")
    table_name = str(lineage.get("table_name") or "table")
    row_identity = lineage.get("row_id")
    if row_identity is None:
        row_identity = lineage.get("row_number")
    return source_id, table_name, str(row_identity if row_identity is not None else fallback)


def _source_observations(
    evidence_result: Any,
    *,
    evidence_rows: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Mapping[str, Any]]:
    """Deduplicate raw source rows repeated by pairwise evidence graph edges.

    An evidence graph naturally repeats a Production row in (Production,
    Quality) and (Production, Maintenance) edges. Pair-level rows remain
    correct for join/reconciliation/association work, but summing them for an
    operational total would double-count the underlying production event. This
    helper reconstructs one canonical observation per source/table/row lineage
    for totals, rankings, snapshots, and freshness.
    """

    if isinstance(evidence_result, Mapping):
        supplied_source_rows = _as_rows(evidence_result.get("_operations_source_rows"))
        if supplied_source_rows:
            # The API builds this private packet from every selected source
            # table, including source-specific safety/logistics/workforce data
            # that deliberately did not form a pairwise correlation edge.
            return supplied_source_rows
    pair_rows = list(evidence_rows or _evidence_rows(evidence_result))
    observations: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    fallback_rows: List[Mapping[str, Any]] = []
    for row_index, row in enumerate(pair_rows):
        source_rows = row.get("source_rows")
        if not isinstance(source_rows, list):
            fallback_rows.append(row)
            continue
        found_source_row = False
        for source_row in source_rows:
            if not isinstance(source_row, Mapping):
                continue
            lineage = source_row.get("lineage")
            values = source_row.get("values")
            if not isinstance(lineage, Mapping) or not isinstance(values, Mapping):
                continue
            found_source_row = True
            key = _source_observation_key(lineage, row_index)
            source_id, table_name, _row_identity = key
            canonical_fields = {
                "%s/%s.%s" % (source_id, table_name, str(name)): value
                for name, value in values.items()
            }
            current = observations.get(key)
            if current is None:
                observations[key] = {
                    "evidence_id": row.get("evidence_id"),
                    "match_status": "source_row",
                    "join_key": row.get("join_key"),
                    "lineage": [dict(lineage)],
                    "fields": canonical_fields,
                }
            else:
                # Preserve a source value once. Graph edges may surface the
                # same source row with different linked partners, not changed
                # source facts; merge only fields absent from the first edge.
                current_fields = current["fields"]
                for name, value in canonical_fields.items():
                    current_fields.setdefault(name, value)
        if not found_source_row:
            fallback_rows.append(row)

    # Plain-row inputs and legacy evidence blobs without source_rows retain
    # their existing shape; dedupe only when row lineage is actually present.
    for row_index, row in enumerate(fallback_rows):
        lineage_items = row.get("lineage")
        if not isinstance(lineage_items, list) or not lineage_items:
            observations[("fallback", "row", str(row_index))] = dict(row)
            continue
        first_lineage = lineage_items[0]
        if not isinstance(first_lineage, Mapping):
            observations[("fallback", "row", str(row_index))] = dict(row)
            continue
        key = _source_observation_key(first_lineage, row_index)
        observations.setdefault(key, dict(row))

    return [observations[key] for key in sorted(observations)]


def _scope_dimensions_from_question(question: str) -> List[str]:
    normalized, _tokens = _question_terms(question)
    dimensions: List[str] = []
    if _contains_any(normalized, ("shift", "crew")):
        dimensions.append("shift")
    if "line" in normalized:
        dimensions.append("line")
    if _contains_any(normalized, ("asset", "machine", "equipment", "device")):
        dimensions.append("asset")
    if _contains_any(normalized, ("facility", "plant", "site")):
        dimensions.append("facility")
    return dimensions


def _query_mentions_specific_dimension_value(normalized_question: str, dimension: str) -> bool:
    """Avoid treating a generic 'which asset?' as a failed asset filter."""

    if dimension == "shift":
        return bool(re.search(r"(?:^|_)(?:day|night|weekend)(?:_|$)", normalized_question))
    if dimension == "line":
        return bool(re.search(r"(?:^|_)line(?:_|id_)?\d+(?:_|$)", normalized_question))
    if dimension == "asset":
        return bool(re.search(r"(?:asset|machine|equipment|device)_[a-z0-9]*\d[a-z0-9_]*", normalized_question))
    if dimension == "facility":
        return bool(re.search(r"(?:facility|plant|site)_[a-z0-9]*\d[a-z0-9_]*", normalized_question))
    return False


def _question_scope(question: str, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Find exact, data-backed asset/line/shift/facility filters in a question."""

    normalized_question, question_tokens = _question_terms(question)
    token_set = set(question_tokens)
    applied: List[Dict[str, Any]] = []
    unmatched: List[str] = []
    for dimension in _scope_dimensions_from_question(question):
        values_by_normalized: Dict[str, str] = {}
        for row in rows:
            for field, value in _fields(row).items():
                if _semantic(field) != dimension or value is None:
                    continue
                display = str(value).strip()
                canonical = _normalise(display)
                if canonical:
                    values_by_normalized.setdefault(canonical, display)
        matches = [
            canonical for canonical in values_by_normalized
            if set(token for token in canonical.split("_") if token).issubset(token_set)
        ]
        if matches:
            applied.append({
                "dimension": dimension,
                "values": sorted(values_by_normalized[value] for value in matches),
                "normalized_values": sorted(matches),
            })
        elif _query_mentions_specific_dimension_value(normalized_question, dimension):
            unmatched.append(dimension)
    return {
        "status": "applied" if applied else ("unmatched" if unmatched else "not_requested"),
        "filters": applied,
        "unmatched_dimensions": unmatched,
        "description": (
            "Applied exact dimension values found in the selected evidence."
            if applied else (
                "A specific operational dimension was requested but no exact source value matched it."
                if unmatched else "No exact asset, line, shift, or facility filter was requested."
            )
        ),
    }


def _filter_rows_by_scope(
    rows: Sequence[Mapping[str, Any]],
    scope: Mapping[str, Any],
) -> List[Mapping[str, Any]]:
    filters = scope.get("filters") if isinstance(scope, Mapping) else None
    if not isinstance(filters, list) or not filters:
        return list(rows)
    selected: List[Mapping[str, Any]] = []
    for row in rows:
        fields = _fields(row)
        include = True
        for filter_spec in filters:
            if not isinstance(filter_spec, Mapping):
                continue
            dimension = str(filter_spec.get("dimension") or "")
            wanted = set(filter_spec.get("normalized_values") or [])
            matching_values = {
                _normalise(value)
                for field, value in fields.items()
                if _semantic(field) == dimension and value is not None
            }
            if not wanted.intersection(matching_values):
                include = False
                break
        if include:
            selected.append(row)
    return selected


def _question_metric_semantic(question: str) -> Optional[str]:
    """Constrain anomaly/change answers when the question names a domain."""

    normalized, _tokens = _question_terms(question)
    if _contains_any(normalized, ("downtime", "down_time", "stop", "loss")):
        return "downtime"
    if _contains_any(normalized, ("quality", "defect", "scrap", "reject", "rework", "yield")):
        return "quality"
    if _contains_any(normalized, ("maintenance", "health", "vibration", "service", "machine", "equipment")):
        return "maintenance"
    if _contains_any(normalized, ("production", "output", "throughput", "oee", "plan", "target")):
        return "production"
    return None


def _fields(row: Mapping[str, Any]) -> Mapping[str, Any]:
    fields = row.get("fields")
    if isinstance(fields, Mapping):
        return fields
    # Plain rows are supported for an easy pre-join preview.  Structural keys
    # are omitted so a row id never accidentally becomes an operational metric.
    return {
        str(key): value
        for key, value in row.items()
        if key not in {"lineage", "source_rows", "evidence_id", "match_status", "join_key"}
    }


def _citation(row: Mapping[str, Any]) -> Dict[str, Any]:
    lineage = row.get("lineage")
    lineage_refs = []
    if isinstance(lineage, list):
        for item in lineage[:4]:
            if not isinstance(item, Mapping):
                continue
            lineage_refs.append({
                "source_id": item.get("source_id"),
                "source_name": item.get("source_name"),
                "table_name": item.get("table_name"),
                "row_number": item.get("row_number"),
                "row_id": item.get("row_id"),
            })
    return {
        "evidence_id": row.get("evidence_id"),
        "match_status": row.get("match_status", "source_row"),
        "join_key": row.get("join_key"),
        "lineage": lineage_refs,
    }


def _citations(rows: Iterable[Mapping[str, Any]], *, fields: Optional[Sequence[str]] = None, limit: int = _MAX_CITATIONS) -> List[Dict[str, Any]]:
    selected: List[Mapping[str, Any]] = []
    wanted = {_terminal_field(field) for field in fields or []}
    for row in rows:
        row_fields = _fields(row)
        if wanted and not wanted.intersection({_terminal_field(key) for key in row_fields}):
            continue
        selected.append(row)
    selected.sort(key=lambda row: str(row.get("evidence_id") or ""))
    return [_citation(row) for row in selected[:max(0, limit)]]


def _analytics_blocks(evidence_result: Any) -> List[Mapping[str, Any]]:
    if not isinstance(evidence_result, Mapping):
        return []
    blocks: List[Mapping[str, Any]] = []
    for key in ("analytics", "operational_analytics"):
        candidate = evidence_result.get(key)
        if isinstance(candidate, Mapping):
            blocks.append(candidate)
    for edge in _as_rows(evidence_result.get("evidence_sets")):
        for key in ("analytics", "operational_analytics"):
            candidate = edge.get(key)
            if isinstance(candidate, Mapping):
                blocks.append(candidate)
    return blocks


def _relationships(evidence_result: Any) -> List[Mapping[str, Any]]:
    results: List[Mapping[str, Any]] = []
    seen = set()
    for block in _analytics_blocks(evidence_result):
        for relation in _as_rows(block.get("relationships")):
            if relation.get("status") != "ok":
                continue
            if _coerce_number(relation.get("pearson_r")) is None:
                continue
            # The same edge analytics can be present in an edge payload and a
            # wrapped graph summary. Do not surface duplicate findings merely
            # because a relationship was serialized through both paths.
            fields = sorted((
                str(relation.get("left_field") or ""),
                str(relation.get("right_field") or ""),
            ))
            signature = (
                tuple(fields),
                _format_number(relation.get("pearson_r")),
                str(relation.get("observation_count") or relation.get("available_observation_count") or ""),
                _format_number(relation.get("association_confidence")),
            )
            if signature in seen:
                continue
            seen.add(signature)
            results.append(relation)
    return sorted(
        results,
        key=lambda relation: (
            -abs(float(_coerce_number(relation.get("pearson_r")) or 0.0)),
            -float(_coerce_number(relation.get("association_confidence")) or 0.0),
            str(relation.get("left_field") or ""),
            str(relation.get("right_field") or ""),
        ),
    )


def _field_signals(evidence_result: Any) -> Dict[str, List[Mapping[str, Any]]]:
    output: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    seen = set()
    for block in _analytics_blocks(evidence_result):
        signals = block.get("field_signals")
        if not isinstance(signals, Mapping):
            continue
        for field, signal in signals.items():
            if isinstance(signal, Mapping):
                signature = (str(field), repr(signal.get("change_point")), repr(signal.get("anomalies")))
                if signature in seen:
                    continue
                seen.add(signature)
                output[str(field)].append(signal)
    return dict(output)


def _semantic(field: Any) -> str:
    token = _terminal_field(field)
    if token in {"asset", "asset_id", "machine", "machine_id", "equipment", "equipment_id", "device", "device_id"}:
        return "asset"
    if token in {"line", "line_id", "production_line", "production_line_id"}:
        return "line"
    if token in {"shift", "shift_name", "shift_code"}:
        return "shift"
    if _contains_any(token, ("downtime", "down_time", "lost_time", "stoppage", "unplanned_stop")):
        return "downtime"
    if _contains_any(token, ("defect", "scrap", "reject", "rework", "yield", "quality", "good_units")):
        return "quality"
    if _contains_any(token, ("maintenance", "health", "vibration", "bearing", "condition", "alarm", "failure")):
        return "maintenance"
    if _contains_any(token, ("incident", "near_miss", "safety", "compliance", "osha", "hazard", "citation")):
        return "safety"
    if _contains_any(token, ("inventory", "stockout", "supplier", "delivery", "shipment", "carrier", "logistics", "detention", "dwell", "trailer", "yard")):
        return "supply"
    if _contains_any(token, ("workforce", "operator", "overtime", "absenteeism", "attendance", "training", "turnover", "headcount", "staff")):
        return "workforce"
    if _contains_any(token, ("output", "actual_units", "units_produced", "production", "throughput", "plan", "target")):
        return "production"
    if _contains_any(token, ("date", "time", "timestamp", "recorded_at")):
        return "time"
    return "other"


def _field_names(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    names: List[str] = []
    seen = set()
    for row in rows:
        for name in _fields(row):
            text = str(name)
            if text not in seen:
                seen.add(text)
                names.append(text)
    return names


def _metric_fields(rows: Sequence[Mapping[str, Any]], semantic: str) -> List[str]:
    counts: Counter = Counter()
    for row in rows:
        for name, value in _fields(row).items():
            if _semantic(name) == semantic and _coerce_number(value) is not None:
                counts[str(name)] += 1
    return sorted(counts, key=lambda name: (-counts[name], str(name)))


def _row_matches_fields(row: Mapping[str, Any], field_names: Sequence[str]) -> bool:
    desired = {str(name) for name in field_names}
    return any(str(name) in desired for name in _fields(row))


def _relationship_statement(relation: Mapping[str, Any]) -> str:
    left = str(relation.get("left_field") or "left metric")
    right = str(relation.get("right_field") or "right metric")
    coefficient = _coerce_number(relation.get("pearson_r"))
    direction = "positive" if coefficient is not None and coefficient > 0 else "negative"
    strength = str(relation.get("strength") or "observed")
    count = relation.get("observation_count") or relation.get("available_observation_count")
    return (
        "%s and %s have a %s %s association (Pearson r=%s, n=%s)."
        % (left, right, strength, direction, _format_number(coefficient), count)
    )


def _format_number(value: Any) -> str:
    numeric = _coerce_number(value)
    if numeric is None:
        return "not available"
    return ("%.3f" % numeric).rstrip("0").rstrip(".")


def _quality_from_result(evidence_result: Any) -> Mapping[str, Any]:
    if isinstance(evidence_result, Mapping):
        quality = evidence_result.get("quality")
        if isinstance(quality, Mapping):
            return quality
    return {}


def _source_profile(evidence_result: Any) -> Mapping[str, Any]:
    if isinstance(evidence_result, Mapping):
        profile = evidence_result.get("source_profile")
        if isinstance(profile, Mapping):
            return profile
    return {}


def _finding(
    finding_id: str,
    title: str,
    statement: str,
    *,
    evidence: Optional[Mapping[str, Any]] = None,
    citations: Optional[List[Dict[str, Any]]] = None,
    uncertainty: Optional[Sequence[str]] = None,
    priority: str = "review",
) -> Dict[str, Any]:
    return {
        "id": finding_id,
        "title": title,
        "statement": statement,
        "priority": priority,
        "evidence": dict(evidence or {}),
        "citations": list(citations or []),
        "uncertainty": list(uncertainty or []),
    }


def _is_observed_event_time_field(field: Any) -> bool:
    """Accept observed event dates, never planned/due/scheduled dates."""

    token = _terminal_field(field)
    if _contains_any(token, ("due", "next", "scheduled", "planned", "plan", "target", "forecast", "expected")):
        return False
    return token in {
        "date", "event_date", "event_time", "timestamp", "datetime",
        "recorded_at", "occurred_at", "start_time", "end_time", "shift_date",
        "production_date", "inspection_date",
    } or _contains_any(token, ("event_time", "timestamp", "recorded_at", "occurred_at"))


def _freshness(rows: Sequence[Mapping[str, Any]], *, as_of: Optional[date]) -> Dict[str, Any]:
    latest: Optional[datetime] = None
    for row in rows:
        for field, value in _fields(row).items():
            if not _is_observed_event_time_field(field):
                continue
            parsed = _parse_date(value)
            if parsed and (latest is None or parsed > latest):
                latest = parsed
    reference = as_of or datetime.now(timezone.utc).date()
    if latest is None:
        return {
            "status": "unknown",
            "latest_event_time": None,
            "historical": None,
            "caveat": "No parseable event date was available; verify that this evidence represents the current shift.",
        }
    age_days = max(0, (reference - latest.date()).days)
    historical = age_days > _HISTORICAL_AFTER_DAYS
    return {
        "status": "ok",
        "latest_event_time": latest.isoformat().replace("+00:00", "Z"),
        "age_days": age_days,
        "historical": historical,
        "caveat": (
            "The newest evidence is %d days old. Treat this as a pattern-review draft, not live control guidance."
            % age_days
            if historical
            else "Data freshness is within the configured review window; still verify live conditions before acting."
        ),
    }


def _parse_date(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = "%s+00:00" % text[:-1]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y/%m/%d")
        except ValueError:
            return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _metric_aggregation(field: str) -> str:
    """Use a transparent aggregation suitable for the field name, if known."""

    token = _terminal_field(field)
    if _contains_any(token, ("rate", "percent", "percentage", "score", "ratio", "ppm", "oee")):
        return "mean"
    return "sum"


def _metric_snapshot(
    rows: Sequence[Mapping[str, Any]],
    semantic: str,
    *,
    finding_id: str,
    title: str,
) -> Optional[Dict[str, Any]]:
    fields = _metric_fields(rows, semantic)
    if not fields:
        return None
    metric = fields[0]
    values: List[Tuple[Mapping[str, Any], float]] = []
    for row in rows:
        value = _coerce_number(_fields(row).get(metric))
        if value is not None:
            values.append((row, value))
    if not values:
        return None
    aggregation = _metric_aggregation(metric)
    total = sum(value for _row, value in values)
    result_value = total / len(values) if aggregation == "mean" else total
    verb = "average" if aggregation == "mean" else "total"
    return _finding(
        finding_id,
        title,
        "%s %s is %s across %d unique source record(s)."
        % (verb.title(), _display_field(metric), _format_number(result_value), len(values)),
        evidence={
            "metric": metric,
            "display_metric": _display_field(metric),
            "aggregation": aggregation,
            "value": round(result_value, 8),
            "source_record_count": len(values),
        },
        citations=_citations([row for row, _value in values], fields=[metric]),
        uncertainty=["Verify the metric definition, unit, and data freshness before comparing it to another measure."],
    )


def _cross_source_relationships(evidence_result: Any) -> List[Mapping[str, Any]]:
    """Prefer a relation spanning two evidence sides for a correlation briefing."""

    return [
        relation for relation in _relationships(evidence_result)
        if str(relation.get("left_field") or "").split(".", 1)[0]
        != str(relation.get("right_field") or "").split(".", 1)[0]
    ]


def _prefer_cross_source_relationships(
    relationships: Sequence[Mapping[str, Any]],
) -> List[Mapping[str, Any]]:
    """Place cross-table signals ahead of within-table metric co-movement."""

    return sorted(
        relationships,
        key=lambda relation: (
            0 if str(relation.get("left_field") or "").split(".", 1)[0]
            != str(relation.get("right_field") or "").split(".", 1)[0]
            else 1,
        ),
    )


def _overview_findings(
    pair_rows: Sequence[Mapping[str, Any]],
    source_rows: Sequence[Mapping[str, Any]],
    evidence_result: Any,
    *,
    include_global_analytics: bool = True,
) -> List[Dict[str, Any]]:
    profile = _source_profile(evidence_result)
    quality = _quality_from_result(evidence_result)
    matched = sum(1 for row in pair_rows if row.get("match_status") == "matched")
    unmatched = sum(1 for row in pair_rows if str(row.get("match_status") or "").startswith("unmatched"))
    findings = [
        _finding(
            "evidence_coverage",
            "Evidence coverage",
            "The briefing uses %d unique source records and %d pairwise evidence rows (%d matched, %d unmatched) across %s source(s) and %s table(s)."
            % (
                len(source_rows), len(pair_rows), matched, unmatched,
                profile.get("source_count", "unknown"), profile.get("table_count", "unknown"),
            ),
            evidence={"unique_source_record_count": len(source_rows), "evidence_row_count": len(pair_rows), "matched_row_count": matched, "unmatched_row_count": unmatched},
            citations=_citations(pair_rows),
            uncertainty=list(quality.get("warnings") or []),
        )
    ]
    for semantic, finding_id, title in (
        ("production", "production_snapshot", "Production signal"),
        ("downtime", "downtime_snapshot", "Downtime signal"),
        ("quality", "quality_snapshot", "Quality signal"),
    ):
        snapshot = _metric_snapshot(source_rows, semantic, finding_id=finding_id, title=title)
        if snapshot:
            findings.append(snapshot)
    relations = _cross_source_relationships(evidence_result) if include_global_analytics else []
    if relations:
        relation = relations[0]
        fields = [str(relation.get("left_field")), str(relation.get("right_field"))]
        findings.append(_finding(
            "strongest_observed_association",
            "Strongest observed association",
            _relationship_statement(relation),
            evidence={"relationship": dict(relation)},
            citations=_citations(pair_rows, fields=fields),
            uncertainty=["This is an observational association, not a root-cause finding."],
        ))
    return findings[:_MAX_FINDINGS]


def _performance_findings(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Summarize plan attainment and throughput without prescribing changes."""

    production_fields = _metric_fields(rows, "production")
    actual_fields = [
        field for field in production_fields
        if _contains_any(_terminal_field(field), ("actual", "output", "produced"))
    ]
    plan_fields = [
        field for field in production_fields
        if _contains_any(_terminal_field(field), ("planned", "plan", "target"))
    ]
    best_pair: Optional[Tuple[str, str, List[Tuple[Mapping[str, Any], float, float]]]] = None
    for actual in actual_fields:
        actual_tokens = set(_terminal_field(actual).split("_"))
        for planned in plan_fields:
            paired: List[Tuple[Mapping[str, Any], float, float]] = []
            for row in rows:
                values = _fields(row)
                actual_value = _coerce_number(values.get(actual))
                planned_value = _coerce_number(values.get(planned))
                if actual_value is not None and planned_value is not None:
                    paired.append((row, actual_value, planned_value))
            if not paired:
                continue
            score = (len(paired), len(actual_tokens.intersection(_terminal_field(planned).split("_"))))
            if best_pair is None:
                best_pair = (actual, planned, paired)
                best_score = score
            elif score > best_score:
                best_pair = (actual, planned, paired)
                best_score = score

    findings: List[Dict[str, Any]] = []
    if best_pair:
        actual, planned, paired = best_pair
        actual_total = sum(value for _row, value, _planned in paired)
        planned_total = sum(value for _row, _actual, value in paired)
        variance = actual_total - planned_total
        variance_percent = (variance / planned_total * 100.0) if planned_total else None
        direction = "above" if variance >= 0 else "below"
        percent_text = "" if variance_percent is None else " (%s%%)" % _format_number(abs(variance_percent))
        findings.append(_finding(
            "plan_attainment",
            "Plan attainment",
            "%s totals %s versus %s planned across %d unique source record(s): %s %s plan%s."
            % (_display_field(actual), _format_number(actual_total), _format_number(planned_total), len(paired), _format_number(abs(variance)), direction, percent_text),
            evidence={
                "actual_field": actual,
                "planned_field": planned,
                "display_metric": "%s vs %s" % (_display_field(actual), _display_field(planned)),
                "actual_total": round(actual_total, 8),
                "planned_total": round(planned_total, 8),
                "variance": round(variance, 8),
                "variance_percent": round(variance_percent, 8) if variance_percent is not None else None,
                "source_record_count": len(paired),
            },
            citations=_citations([row for row, _actual, _planned in paired], fields=[actual, planned]),
            uncertainty=["Plan attainment is descriptive. Confirm the current production plan and constraints before changing output targets."],
            priority="investigate" if variance < 0 else "review",
        ))

    throughput_fields = [
        field for field in production_fields
        if _contains_any(_terminal_field(field), ("throughput", "cycle_time", "oee", "capacity"))
    ]
    if throughput_fields:
        metric = throughput_fields[0]
        values = [
            (row, _coerce_number(_fields(row).get(metric)))
            for row in rows
        ]
        values = [(row, value) for row, value in values if value is not None]
        if values:
            average = sum(value for _row, value in values) / len(values)
            findings.append(_finding(
                "throughput_signal",
                "Throughput/capacity signal",
                "Average %s is %s across %d unique source record(s). A bottleneck is not diagnosed from this signal alone."
                % (_display_field(metric), _format_number(average), len(values)),
                evidence={"metric": metric, "display_metric": _display_field(metric), "aggregation": "mean", "value": round(average, 8), "source_record_count": len(values)},
                citations=_citations([row for row, _value in values], fields=[metric]),
                uncertainty=["Inspect material availability, staffing, machine state, and process constraints before naming a bottleneck or changing output."],
            ))
    if findings:
        return findings[:_MAX_FINDINGS]
    snapshot = _metric_snapshot(rows, "production", finding_id="production_signal", title="Production signal")
    if snapshot:
        snapshot["uncertainty"].append("No comparable actual-versus-plan field pair was found, so plan attainment cannot be calculated.")
        return [snapshot]
    return [_finding(
        "performance_not_available",
        "Performance evidence is unavailable",
        "No numeric production, plan, target, throughput, or capacity field was found in the selected evidence.",
        uncertainty=["Add a stable asset/line/shift key and measurable plan/actual fields for a deterministic performance answer."],
    )]


def _domain_metric_findings(
    rows: Sequence[Mapping[str, Any]],
    *,
    semantic: str,
    title: str,
    preferred_tokens: Sequence[str],
) -> List[Dict[str, Any]]:
    """Give a bounded factual snapshot for a non-causal operations domain."""

    metrics = _metric_fields(rows, semantic)
    metrics.sort(key=lambda field: (
        0 if _contains_any(_terminal_field(field), preferred_tokens) else 1,
        field,
    ))
    findings: List[Dict[str, Any]] = []
    for index, metric in enumerate(metrics[:2], start=1):
        values = [
            (row, _coerce_number(_fields(row).get(metric)))
            for row in rows
        ]
        values = [(row, value) for row, value in values if value is not None]
        if not values:
            continue
        aggregation = _metric_aggregation(metric)
        total = sum(value for _row, value in values)
        result_value = total / len(values) if aggregation == "mean" else total
        verb = "Average" if aggregation == "mean" else "Total"
        findings.append(_finding(
            "%s_metric_%d" % (semantic, index),
            title,
            "%s %s is %s across %d unique source record(s)."
            % (verb, _display_field(metric), _format_number(result_value), len(values)),
            evidence={
                "metric": metric,
                "display_metric": _display_field(metric),
                "aggregation": aggregation,
                "value": round(result_value, 8),
                "source_record_count": len(values),
            },
            citations=_citations([row for row, _value in values], fields=[metric]),
            uncertainty=["This is a measured review signal. Verify current conditions and the source definition before declaring a risk, constraint, or corrective action."],
            priority="investigate" if semantic in {"safety", "supply"} else "review",
        ))
    if findings:
        return findings
    present = [name for name in _field_names(rows) if _semantic(name) == semantic]
    if present:
        return [_finding(
            "%s_fields_present" % semantic,
            "%s evidence is present" % title,
            "The selected evidence contains %s fields (%s), but no numeric metric can be aggregated safely."
            % (title.casefold(), ", ".join(_display_field(field) for field in present[:4])),
            citations=_citations(rows, fields=present),
            uncertainty=["Review the cited records directly; no numeric score was invented from categorical fields."],
        )]
    return [_finding(
        "%s_not_available" % semantic,
        "%s evidence is unavailable" % title,
        "No recognized %s field was found in the selected evidence."
        % title.casefold(),
        uncertainty=["Select the relevant operational table or add stable, typed fields for this domain."],
    )]


def _downtime_findings(
    pair_rows: Sequence[Mapping[str, Any]],
    source_rows: Sequence[Mapping[str, Any]],
    evidence_result: Any,
    *,
    include_global_analytics: bool = True,
) -> List[Dict[str, Any]]:
    downtime_fields = _metric_fields(source_rows, "downtime")
    findings: List[Dict[str, Any]] = []
    if not downtime_fields:
        return [_finding(
            "downtime_not_available",
            "Downtime evidence is unavailable",
            "No numeric downtime field was found in the supplied evidence, so the service will not guess at downtime drivers.",
            uncertainty=["Add a downtime duration/count field and a stable asset/time key to investigate observed associations."],
        )]
    related = _prefer_cross_source_relationships([
        relation for relation in _relationships(evidence_result)
        if _semantic(relation.get("left_field")) == "downtime" or _semantic(relation.get("right_field")) == "downtime"
    ]) if include_global_analytics else []
    if not related:
        scope_note = (
            " The requested dimension filter was applied to source records, but association analytics must be recomputed on that scoped subset."
            if not include_global_analytics
            else ""
        )
        findings.append(_finding(
            "downtime_measurement",
            "Downtime is present but not analytically linked",
            "Downtime fields are present (%s), but no eligible analytics relationship was supplied for them.%s"
            % (", ".join(_display_field(field) for field in downtime_fields[:3]), scope_note),
            citations=_citations(source_rows, fields=downtime_fields),
            uncertainty=["Run bounded analytics on a confirmed common evidence table before ranking observed drivers."],
        ))
    for index, relation in enumerate(related[:_MAX_FINDINGS], start=1):
        fields = [str(relation.get("left_field")), str(relation.get("right_field"))]
        other = fields[1] if _semantic(fields[0]) == "downtime" else fields[0]
        findings.append(_finding(
            "downtime_association_%d" % index,
            "Observed downtime association",
            "%s appears associated with downtime: %s" % (other, _relationship_statement(relation)),
            evidence={"relationship": dict(relation), "downtime_fields": downtime_fields},
            citations=_citations(pair_rows, fields=fields),
            uncertainty=["Investigate this signal; correlation and lead/lag do not establish that %s caused downtime." % other],
            priority="investigate",
        ))
    if include_global_analytics:
        changes = _change_findings(pair_rows, evidence_result, only_semantic="downtime")
        findings.extend(changes[: max(0, _MAX_FINDINGS - len(findings))])
    return findings[:_MAX_FINDINGS]


def _change_findings(
    rows: Sequence[Mapping[str, Any]],
    evidence_result: Any,
    *,
    only_semantic: Optional[str] = None,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    signals = _field_signals(evidence_result)
    candidates: List[Tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    seen_candidates = set()
    for field, records in signals.items():
        if only_semantic and _semantic(field) != only_semantic:
            continue
        for signal in records:
            change = signal.get("change_point")
            if isinstance(change, Mapping) and isinstance(change.get("change_point"), Mapping):
                point = change["change_point"]
                signature = (
                    field,
                    point.get("source_index", point.get("index")),
                    _format_number(point.get("left_mean")),
                    _format_number(point.get("right_mean")),
                    _format_number(point.get("mean_delta")),
                )
                if signature not in seen_candidates:
                    seen_candidates.add(signature)
                    candidates.append((field, change, point))
    candidates.sort(key=lambda item: (-abs(float(_coerce_number(item[2].get("mean_delta")) or 0.0)), item[0]))
    for index, (field, change, point) in enumerate(candidates[:_MAX_FINDINGS], start=1):
        statement = (
            "%s has a mean-shift candidate at source position %s: average changed from %s to %s (delta %s)."
            % (
                field, point.get("source_index", point.get("index")),
                _format_number(point.get("left_mean")), _format_number(point.get("right_mean")),
                _format_number(point.get("mean_delta")),
            )
        )
        findings.append(_finding(
            "change_candidate_%d" % index,
            "Change candidate",
            statement,
            evidence={"field": field, "change_point": dict(point), "analysis": dict(change)},
            citations=_citations(rows, fields=[field]),
            uncertainty=[str(change.get("interpretation") or "A change candidate is a review signal, not an identified cause.")],
            priority="investigate",
        ))
    if not findings and not only_semantic:
        # Anomaly detection is still useful if no mean shift met the threshold.
        anomaly_candidates: List[Tuple[str, Mapping[str, Any]]] = []
        seen_anomalies = set()
        for field, records in signals.items():
            for signal in records:
                anomaly = signal.get("anomalies")
                if isinstance(anomaly, Mapping):
                    for item in _as_rows(anomaly.get("anomalies")):
                        signature = (
                            field,
                            item.get("source_index", item.get("index")),
                            _format_number(item.get("value")),
                            _format_number(item.get("score")),
                        )
                        if signature not in seen_anomalies:
                            seen_anomalies.add(signature)
                            anomaly_candidates.append((field, item))
        anomaly_candidates.sort(key=lambda item: (-abs(float(_coerce_number(item[1].get("score")) or 0.0)), item[0]))
        for index, (field, anomaly) in enumerate(anomaly_candidates[:_MAX_FINDINGS], start=1):
            findings.append(_finding(
                "anomaly_candidate_%d" % index,
                "Outlier requiring review",
                "%s has a %s outlier (value %s, score %s)."
                % (field, anomaly.get("direction", "detected"), _format_number(anomaly.get("value")), _format_number(anomaly.get("score"))),
                evidence={"field": field, "anomaly": dict(anomaly)},
                citations=_citations(rows, fields=[field]),
                uncertainty=["An outlier is a review signal, not a diagnosis."],
                priority="investigate",
            ))
    if not findings:
        return [_finding(
            "no_change_candidate",
            "No eligible change signal",
            "No supplied field passed the configured deterministic change/anomaly review threshold.",
            uncertainty=["This does not prove operations were stable; it only describes the available bounded evidence."],
        )]
    return findings


def _requested_dimensions(question: str, rows: Sequence[Mapping[str, Any]]) -> List[Tuple[str, List[str]]]:
    """Return every explicitly requested asset/line/shift breakdown.

    A question such as "asset, line, or shift" should not silently become only
    a shift answer. When no dimension is named, asset remains the conservative
    default, followed by available operational dimensions as a fallback.
    """

    normalized, _tokens = _question_terms(question)
    requested: List[str] = []
    if _contains_any(normalized, ("asset", "machine", "equipment", "device")):
        requested.append("asset")
    if "line" in normalized:
        requested.append("line")
    if "shift" in normalized or "crew" in normalized:
        requested.append("shift")
    if not requested:
        requested = ["asset"]

    results: List[Tuple[str, List[str]]] = []
    for dimension in requested:
        fields = [name for name in _field_names(rows) if _semantic(name) == dimension]
        if fields:
            results.append((dimension, fields))
    if results:
        return results
    for fallback in ("asset", "line", "shift"):
        fields = [name for name in _field_names(rows) if _semantic(name) == fallback]
        if fields:
            return [(fallback, fields)]
    return [(requested[0], [])]


def _choose_priority_metric(rows: Sequence[Mapping[str, Any]], *, preference: Optional[str] = None) -> Optional[str]:
    semantic_order = [preference] if preference else []
    semantic_order.extend([semantic for semantic in ("downtime", "quality", "maintenance") if semantic not in semantic_order])
    for semantic in semantic_order:
        if not semantic:
            continue
        candidates = _metric_fields(rows, semantic)
        if candidates:
            # Prefer a left/right matched field with the most numeric coverage;
            # no cross-unit score is created.
            return candidates[0]
    return None


def _values_for_dimension(row: Mapping[str, Any], dimension_fields: Sequence[str]) -> List[str]:
    names = set(dimension_fields)
    values: List[str] = []
    for name, value in _fields(row).items():
        if str(name) not in names or value is None:
            continue
        value_text = str(value).strip()
        if value_text and value_text not in values:
            values.append(value_text)
    return values


def _priority_findings(question: str, rows: Sequence[Mapping[str, Any]], *, preference: Optional[str] = None) -> List[Dict[str, Any]]:
    metric = _choose_priority_metric(rows, preference=preference)
    dimensions = _requested_dimensions(question, rows)
    if not metric or not any(fields for _dimension, fields in dimensions):
        return [_finding(
            "priority_not_available",
            "Prioritization is unavailable",
            "A numeric downtime, quality, or maintenance metric and an asset/line/shift field are both required for a deterministic priority ranking.",
            uncertainty=["No priority score was invented from incompatible units or unlinked source tables."],
        )]
    findings: List[Dict[str, Any]] = []
    per_dimension_limit = _MAX_FINDINGS if len(dimensions) == 1 else max(1, _MAX_FINDINGS // len(dimensions))
    for dimension, dimension_fields in dimensions:
        if not dimension_fields:
            continue
        totals: Dict[str, float] = defaultdict(float)
        counts: Counter = Counter()
        supporting_rows: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            value = _coerce_number(_fields(row).get(metric))
            if value is None:
                continue
            for entity in _values_for_dimension(row, dimension_fields):
                totals[entity] += value
                counts[entity] += 1
                supporting_rows[entity].append(row)
        ranked = sorted(totals, key=lambda entity: (-totals[entity], entity))[:per_dimension_limit]
        only_one_entity = len(totals) == 1
        for rank, entity in enumerate(ranked, start=1):
            comparison_note = (
                " Only one distinct %s is present, so this is a single-entity review item rather than a comparative ranking."
                % dimension
                if only_one_entity
                else ""
            )
            findings.append(_finding(
                "priority_%s_%d" % (dimension, rank),
                "%s priority %d" % (dimension.title(), rank),
                "%s %s ranks %d by summed %s: %s across %d unique source record(s).%s"
                % (dimension.title(), entity, rank, _display_field(metric), _format_number(totals[entity]), counts[entity], comparison_note),
                evidence={
                    "dimension": dimension,
                    "entity": entity,
                    "metric": metric,
                    "display_metric": _display_field(metric),
                    "aggregation": "sum",
                    "value": round(totals[entity], 8),
                    "row_count": counts[entity],
                    "comparative_ranking": not only_one_entity,
                },
                citations=_citations(supporting_rows[entity], fields=[metric]),
                uncertainty=["This is a transparent priority ranking by one source metric; verify its unit and current state before assigning work."],
                priority="review_first" if rank == 1 else "review",
            ))
        if len(findings) >= _MAX_FINDINGS:
            break
    return findings or [_finding(
        "priority_no_numeric_values",
        "Priority values are unavailable",
        "The selected priority metric has no usable numeric values linked to the requested entity.",
    )]


def _quality_findings(
    rows: Sequence[Mapping[str, Any]],
    *,
    source_rows: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    names = _field_names(rows)
    left_by_terminal = { _terminal_field(name): name for name in names if str(name).startswith("left.") }
    right_by_terminal = { _terminal_field(name): name for name in names if str(name).startswith("right.") }
    comparable = sorted(
        terminal for terminal in set(left_by_terminal).intersection(right_by_terminal)
        if _semantic(terminal) == "quality"
    )
    findings: List[Dict[str, Any]] = []
    for terminal in comparable[:_MAX_FINDINGS]:
        left_name, right_name = left_by_terminal[terminal], right_by_terminal[terminal]
        compared = 0
        mismatches: List[Mapping[str, Any]] = []
        for row in rows:
            if row.get("match_status") not in {None, "matched"}:
                continue
            values = _fields(row)
            left, right = values.get(left_name), values.get(right_name)
            if left is None or right is None:
                continue
            compared += 1
            left_num, right_num = _coerce_number(left), _coerce_number(right)
            if left_num is not None and right_num is not None:
                same = math.isclose(left_num, right_num, rel_tol=1e-9, abs_tol=1e-9)
            else:
                same = _normalise(left) == _normalise(right)
            if not same:
                mismatches.append(row)
        if not compared:
            continue
        mismatch_rate = len(mismatches) / compared
        findings.append(_finding(
            "quality_reconciliation_%s" % terminal,
            "Quality reconciliation: %s" % terminal,
            "%d of %d matched records disagree on %s (%.1f%% mismatch rate)."
            % (len(mismatches), compared, terminal, mismatch_rate * 100.0),
            evidence={
                "field": terminal,
                "left_field": left_name,
                "right_field": right_name,
                "compared_row_count": compared,
                "mismatch_count": len(mismatches),
                "mismatch_rate": round(mismatch_rate, 8),
            },
            citations=_citations(mismatches or rows, fields=[left_name, right_name]),
            uncertainty=["A disagreement is a reconciliation task. It does not identify which source is correct."],
            priority="investigate" if mismatches else "review",
        ))
    if findings:
        return findings
    quality_rows = list(source_rows) if source_rows is not None else list(rows)
    quality_fields = _metric_fields(quality_rows, "quality")
    if quality_fields:
        snapshot = _metric_snapshot(
            quality_rows,
            "quality",
            finding_id="quality_signal_without_reconciliation",
            title="Quality metrics are present",
        )
        if snapshot:
            snapshot["uncertainty"].append("No same-named left/right matched field was available for deterministic reconciliation.")
            return [snapshot]
    return [_finding(
        "quality_not_available",
        "Quality evidence is unavailable",
        "No recognized defect, scrap, reject, rework, yield, or quality field was found in the supplied evidence.",
    )]


def _maintenance_findings(
    question: str,
    pair_rows: Sequence[Mapping[str, Any]],
    source_rows: Sequence[Mapping[str, Any]],
    evidence_result: Any,
    *,
    include_global_analytics: bool = True,
) -> List[Dict[str, Any]]:
    maintenance_fields = _metric_fields(source_rows, "maintenance")
    if not maintenance_fields:
        return [_finding(
            "maintenance_not_available",
            "Maintenance-risk evidence is unavailable",
            "No numeric maintenance/condition field was found, so the service will not manufacture an asset-risk ranking.",
            uncertainty=["Add a maintenance-health, condition, vibration, alarm, or work-order metric linked by asset and time."],
        )]
    findings: List[Dict[str, Any]] = []
    related = _prefer_cross_source_relationships([
        relation for relation in _relationships(evidence_result)
        if _semantic(relation.get("left_field")) == "maintenance" or _semantic(relation.get("right_field")) == "maintenance"
    ]) if include_global_analytics else []
    for index, relation in enumerate(related[:2], start=1):
        fields = [str(relation.get("left_field")), str(relation.get("right_field"))]
        maintenance_field = fields[0] if _semantic(fields[0]) == "maintenance" else fields[1]
        other = fields[1] if maintenance_field == fields[0] else fields[0]
        findings.append(_finding(
            "maintenance_association_%d" % index,
            "Maintenance condition to investigate",
            "%s is associated with %s: %s" % (maintenance_field, other, _relationship_statement(relation)),
            evidence={"relationship": dict(relation)},
            citations=_citations(pair_rows, fields=fields),
            uncertainty=["Condition metrics can flag where to inspect; they do not predict a failure with certainty or prove a cause."],
            priority="investigate",
        ))
    findings.extend(_priority_findings(question, source_rows, preference="maintenance")[: max(0, _MAX_FINDINGS - len(findings))])
    return findings[:_MAX_FINDINGS]


def _approval_block(
    *,
    freshness: Mapping[str, Any],
    quality: Mapping[str, Any],
    source_rows_truncated: bool = False,
) -> Dict[str, Any]:
    conditions = [
        "Verify the cited source rows and definitions before assigning work.",
        "Confirm current equipment/line/shift conditions with the supervisor or control system.",
        "Assign an owner, due time, and completion evidence for every approved task.",
        "Require a human approval before any operational action or automated escalation.",
    ]
    if freshness.get("historical") is True:
        conditions.insert(0, "Validate the pattern against live shift data; historical evidence is not live control guidance.")
    if quality.get("review_required"):
        conditions.insert(0, "Review the join plan and data-quality warnings before relying on totals or rankings.")
    if source_rows_truncated:
        conditions.insert(0, "The operations source packet was bounded; treat totals as a sampled review scope and rerun an approved full job before making a material decision.")
    return {
        "required": True,
        "state": "pending_human_approval",
        "approval_conditions": conditions,
        "prohibited_without_approval": [
            "Claiming an observed association is a root cause",
            "Changing equipment setpoints or production plans",
            "Closing a maintenance or quality issue",
            "Automatically assigning work or escalating an incident",
        ],
    }


def _checklist_from_findings(
    findings: Sequence[Mapping[str, Any]],
    *,
    freshness: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if freshness.get("historical") is True or freshness.get("status") == "unknown":
        items.append({
            "id": "verify_data_freshness",
            "priority": "before_shift",
            "task": "Verify live conditions and current-shift data before using this draft.",
            "why": str(freshness.get("caveat")),
            "citations": [],
            "requires_human_approval": True,
        })
    for finding in findings:
        finding_id = str(finding.get("id") or "finding")
        title = str(finding.get("title") or "evidence finding")
        if finding_id.startswith("priority_"):
            task = "Inspect and confirm the condition of the ranked %s before shift start." % title.lower().replace(" priority", "")
        elif "reconciliation" in finding_id:
            task = "Reconcile the cited quality records and confirm the source-of-record before reporting yield/scrap."
        elif "association" in finding_id:
            task = "Inspect the cited metric and downtime/condition context; record a supervisor-approved finding rather than assuming a cause."
        elif "change" in finding_id or "anomaly" in finding_id:
            task = "Review the cited change/outlier against current logs and confirm whether it is still present."
        else:
            continue
        items.append({
            "id": "check_%s" % finding_id,
            "priority": finding.get("priority", "review"),
            "task": task,
            "why": finding.get("statement"),
            "citations": list(finding.get("citations") or []),
            "requires_human_approval": True,
        })
        if len(items) >= _MAX_FINDINGS:
            break
    if not items:
        items.append({
            "id": "confirm_operating_state",
            "priority": "before_shift",
            "task": "Confirm current operating state, data completeness, and ownership with the shift supervisor.",
            "why": "No sufficiently specific evidence-backed inspection task was available.",
            "citations": [],
            "requires_human_approval": True,
        })
    return items


def _stable_finding(finding: Mapping[str, Any]) -> Dict[str, Any]:
    """Add compact UI/API aliases without dropping the full audit record."""
    output = dict(finding)
    output["detail"] = str(finding.get("statement") or "")
    evidence = finding.get("evidence")
    if isinstance(evidence, Mapping):
        metric = evidence.get("display_metric") or evidence.get("metric") or evidence.get("field")
        if metric is None and isinstance(evidence.get("relationship"), Mapping):
            relation = evidence["relationship"]
            metric = "%s <> %s" % (relation.get("left_field"), relation.get("right_field"))
        output["metric"] = metric
    else:
        output["metric"] = None
    output["evidence_ids"] = [
        citation.get("evidence_id")
        for citation in finding.get("citations") or []
        if isinstance(citation, Mapping) and citation.get("evidence_id")
    ]
    return output


def _stable_checklist_item(item: Mapping[str, Any]) -> Dict[str, Any]:
    """Expose a supervisor-friendly checklist contract alongside audit fields."""
    output = dict(item)
    output["action"] = str(item.get("task") or "")
    output["owner"] = "unassigned — supervisor approval required"
    output["evidence_ids"] = [
        citation.get("evidence_id")
        for citation in item.get("citations") or []
        if isinstance(citation, Mapping) and citation.get("evidence_id")
    ]
    return output


def _stable_response_contract(response: Dict[str, Any]) -> Dict[str, Any]:
    """Return the intentionally small stable surface used by API/UI callers.

    The richer legacy-style keys remain available (``headline``, ``statement``,
    ``next_shift_checklist``, and full citation lineage), while these aliases
    make rendering independent of the detailed evidence representation.
    """
    classification = response.get("classification")
    intent = classification.get("intent") if isinstance(classification, Mapping) else QUESTION_UNSUPPORTED
    response["intent"] = intent
    response["title"] = str(response.get("headline") or "")
    findings = [
        _stable_finding(finding)
        for finding in response.get("findings") or []
        if isinstance(finding, Mapping)
    ]
    response["findings"] = findings
    citations: List[Dict[str, Any]] = []
    seen = set()
    for finding in findings:
        for citation in finding.get("citations") or []:
            if not isinstance(citation, Mapping):
                continue
            evidence_id = str(citation.get("evidence_id") or "")
            key = evidence_id or str(citation.get("lineage") or "")
            if key in seen:
                continue
            seen.add(key)
            citations.append(dict(citation))
    response["citations"] = citations
    checklist = [
        _stable_checklist_item(item)
        for item in response.get("next_shift_checklist") or []
        if isinstance(item, Mapping)
    ]
    response["next_shift_checklist"] = checklist
    response["checklist"] = checklist
    response["guardrails"] = {
        "causation": response.get("causation_guardrail"),
        "human_approval": response.get("human_approval"),
    }
    return response


def answer_operations_question(
    question: Any,
    evidence_result: Any,
    company_name: Optional[str] = None,
    *,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """Answer an operations question using only supplied deterministic evidence.

    Parameters
    ----------
    question:
        A natural-language operations-lead question.  It is classified using
        the documented phrase catalog, not a model.
    evidence_result:
        A direct evidence result, evidence graph result, or a list of evidence
        rows.  Analytics must already be present in the result if association,
        anomaly, or change-point findings are desired.
    company_name:
        Optional presentation label.  It never changes the evidence or joins.
    as_of:
        Optional date used only for reproducible data-freshness warnings.
    """
    classification = classify_operations_question(question)
    pair_rows = _evidence_rows(evidence_result)
    source_rows = _source_observations(evidence_result, evidence_rows=pair_rows)
    operations_source_scope = (
        evidence_result.get("_operations_source_scope")
        if isinstance(evidence_result, Mapping) and isinstance(evidence_result.get("_operations_source_scope"), Mapping)
        else {}
    )
    scope = _question_scope(str(question or ""), source_rows or pair_rows)
    scoped_pair_rows = _filter_rows_by_scope(pair_rows, scope)
    scoped_source_rows = _filter_rows_by_scope(source_rows, scope)
    quality = _quality_from_result(evidence_result)
    freshness = _freshness(scoped_source_rows, as_of=as_of)
    company = str(company_name).strip() if company_name else "the selected operation"
    base: Dict[str, Any] = {
        "status": "ok" if (pair_rows or source_rows) else "insufficient_evidence",
        "question": str(question or "").strip(),
        "company_name": company_name,
        "classification": classification,
        "input_summary": {
            "pairwise_evidence_row_count": len(pair_rows),
            "evidence_row_count": len(scoped_pair_rows),
            "unique_source_record_count": len(scoped_source_rows),
            "matched_row_count": sum(1 for row in scoped_pair_rows if row.get("match_status") == "matched"),
            "source_count": _source_profile(evidence_result).get("source_count"),
            "table_count": _source_profile(evidence_result).get("table_count"),
            "analytics_block_count": len(_analytics_blocks(evidence_result)),
            "evidence_quality": dict(quality),
            "operations_source_scope": dict(operations_source_scope),
        },
        "data_freshness": freshness,
        "scope_filter": scope,
        "causation_guardrail": causation_guardrail(0.0),
        "human_approval": _approval_block(
            freshness=freshness,
            quality=quality,
            source_rows_truncated=bool(operations_source_scope.get("truncated")),
        ),
        "suggested_questions": suggested_operations_questions(),
    }
    if classification["intent"] == QUESTION_UNSUPPORTED:
        base.update({
            "status": "needs_clarification",
            "headline": "Ask a supported operations evidence question.",
            "summary": classification["reason"],
            "findings": [],
            "next_shift_checklist": [],
        })
        return _stable_response_contract(base)
    if not pair_rows and not source_rows:
        base.update({
            "headline": "There is not enough structured evidence to answer this yet.",
            "summary": "Upload/select readable source tables and build a deterministic evidence table before requesting an operations briefing.",
            "findings": [],
            "next_shift_checklist": [],
        })
        return _stable_response_contract(base)
    if scope.get("status") == "unmatched":
        base.update({
            "status": "needs_clarification",
            "headline": "Confirm the requested operational filter before answering.",
            "summary": (
                "The request names a specific %s, but no exact matching value was found in the selected evidence. "
                "The full evidence scope was not used as a substitute."
                % ", ".join(scope.get("unmatched_dimensions") or ["dimension"])
            ),
            "findings": [],
            "next_shift_checklist": [],
        })
        return _stable_response_contract(base)
    if not scoped_source_rows and not scoped_pair_rows:
        base.update({
            "status": "insufficient_evidence",
            "headline": "The requested evidence scope contains no matching records.",
            "summary": "The exact requested filter was applied, but no source records remained. The full evidence scope was not substituted.",
            "findings": [],
            "next_shift_checklist": [],
        })
        return _stable_response_contract(base)

    intent = classification["intent"]
    use_global_analytics = scope.get("status") != "applied"
    if intent == QUESTION_OVERVIEW:
        findings = _overview_findings(
            scoped_pair_rows,
            scoped_source_rows,
            evidence_result,
            include_global_analytics=use_global_analytics,
        )
        headline = "Operations overview for %s" % company
        summary = "A bounded evidence briefing with unique-source totals, record-link quality, and the strongest supplied review signals."
    elif intent == QUESTION_DOWNTIME:
        findings = _downtime_findings(
            scoped_pair_rows,
            scoped_source_rows,
            evidence_result,
            include_global_analytics=use_global_analytics,
        )
        headline = "Downtime investigation signals for %s" % company
        summary = "Potential drivers are measured associations only; they require operational investigation."
    elif intent == QUESTION_CHANGED:
        requested_metric_semantic = _question_metric_semantic(str(question or ""))
        findings = (_change_findings(
            scoped_pair_rows,
            evidence_result,
            only_semantic=requested_metric_semantic,
        ) if use_global_analytics else [
            _finding(
                "scoped_change_analysis_required",
                "Scoped change analysis required",
                "The requested dimension filter was applied to the source records, but change/anomaly analytics were calculated on the full evidence scope and are not reused as if they were scoped.",
                uncertainty=["Rerun bounded analytics on this exact filtered scope before interpreting a change or anomaly."],
            )
        ])
        headline = "What changed in %s" % company
        summary = "Only configured deterministic change-point and anomaly signals are shown."
    elif intent == QUESTION_PRIORITY:
        findings = _priority_findings(str(question or ""), scoped_source_rows)
        headline = "Evidence-backed review priorities for %s" % company
        summary = "Priorities use one transparent metric rather than an opaque cross-unit risk score."
    elif intent == QUESTION_QUALITY:
        findings = _quality_findings(scoped_pair_rows, source_rows=scoped_source_rows)
        headline = "Quality and reconciliation review for %s" % company
        summary = "The service compares matched source records; it does not decide which system is correct."
    elif intent == QUESTION_MAINTENANCE:
        findings = _maintenance_findings(
            str(question or ""),
            scoped_pair_rows,
            scoped_source_rows,
            evidence_result,
            include_global_analytics=use_global_analytics,
        )
        headline = "Maintenance-risk review for %s" % company
        summary = "Condition signals identify where to inspect, not a confirmed failure cause or prediction."
    elif intent == QUESTION_PERFORMANCE:
        findings = _performance_findings(scoped_source_rows)
        headline = "Performance and bottleneck review for %s" % company
        summary = "Plan/actual and throughput signals are descriptive evidence; they do not authorize production-plan or setpoint changes."
    elif intent == QUESTION_SAFETY:
        findings = _domain_metric_findings(
            scoped_source_rows,
            semantic="safety",
            title="Safety and compliance",
            preferred_tokens=("incident", "near_miss", "violation", "citation"),
        )
        headline = "Safety and compliance review for %s" % company
        summary = "Safety findings are evidence for review and escalation through the approved safety process, not an automated determination of safe operating conditions."
    elif intent == QUESTION_SUPPLY:
        findings = _domain_metric_findings(
            scoped_source_rows,
            semantic="supply",
            title="Supply and logistics",
            preferred_tokens=("stockout", "detention", "delivery", "inventory", "dwell"),
        )
        headline = "Supply and logistics review for %s" % company
        summary = "The service reports observed flow signals; it does not declare a material constraint or change a purchasing/production plan automatically."
    elif intent == QUESTION_WORKFORCE:
        findings = _domain_metric_findings(
            scoped_source_rows,
            semantic="workforce",
            title="Workforce readiness",
            preferred_tokens=("absenteeism", "overtime", "operator", "training"),
        )
        headline = "Workforce readiness review for %s" % company
        summary = "The service reports measured staffing signals; a supervisor must confirm current coverage, qualifications, and labor policy before assigning work."
    else:  # QUESTION_CHECKLIST
        seed = _downtime_findings(
            scoped_pair_rows,
            scoped_source_rows,
            evidence_result,
            include_global_analytics=use_global_analytics,
        )
        seed.extend(_quality_findings(scoped_pair_rows, source_rows=scoped_source_rows)[:1])
        seed.extend(_priority_findings(str(question or ""), scoped_source_rows)[:2])
        findings = seed[:_MAX_FINDINGS]
        headline = "Draft next-shift checklist for %s" % company
        summary = "This is a supervisor-approved pattern-review checklist, not an automated control instruction."

    checklist = _checklist_from_findings(findings, freshness=freshness) if intent == QUESTION_CHECKLIST else []
    base.update({
        "headline": headline,
        "summary": summary,
        "findings": findings,
        "next_shift_checklist": checklist,
    })
    return _stable_response_contract(base)


__all__ = [
    "QUESTION_CHANGED",
    "QUESTION_CHECKLIST",
    "QUESTION_DOWNTIME",
    "QUESTION_MAINTENANCE",
    "QUESTION_OVERVIEW",
    "QUESTION_PERFORMANCE",
    "QUESTION_PRIORITY",
    "QUESTION_QUALITY",
    "QUESTION_SAFETY",
    "QUESTION_SUPPLY",
    "QUESTION_UNSUPPORTED",
    "QUESTION_WORKFORCE",
    "answer_operations_question",
    "classify_operations_question",
    "suggested_operations_questions",
]
