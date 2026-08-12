"""Bounded, deterministic analytics for lineage-aware operational evidence.

This module is deliberately statistical rather than generative.  It can help a
reviewer find an association, a leading/lagging signal, an outlier, or a mean
shift in an already-approved common evidence table.  It never upgrades an
observational correlation into a causal claim.

The functions accept ordinary mapping rows so they can be used with spreadsheet
intake, Arrow/Parquet adapters, database batches, and the evidence engine
without a framework dependency.  Work is capped by :class:`OperationalAnalyticsLimits`
to keep a large upload from turning a preview request into an unbounded job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from itertools import combinations
import math
import statistics
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, TypeVar

from app.services.shared_key_detector import normalize_column_header


_TIME_FIELD_HINTS = (
    "event_time",
    "event_timestamp",
    "timestamp",
    "datetime",
    "recorded_at",
    "created_at",
    "time",
    "date",
)
_EPSILON = 1e-12
_MAX_SCORE = 1_000_000.0
_T = TypeVar("_T")


@dataclass(frozen=True)
class OperationalAnalyticsLimits:
    """Explicit resource and statistical guardrails for an analysis run.

    ``max_rows`` and ``max_series_points`` are intentionally separate: callers
    can use many rows for field coverage while each O(pairs * lags * points)
    calculation remains bounded and reproducible through even sampling.
    """

    max_rows: int = 50_000
    max_numeric_fields: int = 20
    max_pair_analyses: int = 60
    max_series_points: int = 5_000
    max_lag_steps: int = 24
    min_observations: int = 6
    anomaly_z_threshold: float = 3.5
    min_change_segment: int = 6
    change_score_threshold: float = 2.5
    max_anomalies_per_field: int = 100


def _positive_int(value: int, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _positive_float(value: float, default: float, minimum: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(numeric):
        return default
    return max(minimum, numeric)


def _normalised_limits(limits: Optional[OperationalAnalyticsLimits]) -> OperationalAnalyticsLimits:
    raw = limits or OperationalAnalyticsLimits()
    return OperationalAnalyticsLimits(
        max_rows=_positive_int(raw.max_rows, 50_000),
        max_numeric_fields=_positive_int(raw.max_numeric_fields, 20),
        max_pair_analyses=_positive_int(raw.max_pair_analyses, 60),
        max_series_points=_positive_int(raw.max_series_points, 5_000),
        max_lag_steps=_positive_int(raw.max_lag_steps, 24, minimum=0),
        min_observations=_positive_int(raw.min_observations, 6, minimum=2),
        anomaly_z_threshold=_positive_float(raw.anomaly_z_threshold, 3.5, minimum=0.1),
        min_change_segment=_positive_int(raw.min_change_segment, 6, minimum=2),
        change_score_threshold=_positive_float(raw.change_score_threshold, 2.5, minimum=0.1),
        max_anomalies_per_field=_positive_int(raw.max_anomalies_per_field, 100),
    )


def _coerce_number(value: Any) -> Optional[float]:
    """Return a finite number without treating booleans as operational metrics."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        # Percentages are a useful spreadsheet convention.  They become a
        # fraction, not an invented unit conversion.
        multiplier = 0.01 if text.endswith("%") else 1.0
        if text.endswith("%"):
            text = text[:-1].strip()
        try:
            numeric = float(text) * multiplier
        except ValueError:
            return None
    else:
        return None
    return numeric if math.isfinite(numeric) else None


def _parse_time(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            # Common unambiguous spreadsheet variants.  Deliberately do not
            # guess between mm/dd and dd/mm formats.
            parsed = None
            for format_string in ("%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    parsed = datetime.strptime(text, format_string)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _field_hint(name: str) -> str:
    return normalize_column_header(str(name).replace(".", "_"))


def _looks_like_time_field(name: str) -> bool:
    normalized = _field_hint(name)
    return normalized in _TIME_FIELD_HINTS or any(
        normalized.endswith(f"_{hint}") for hint in _TIME_FIELD_HINTS
    )


def _json_number(value: Optional[float]) -> Optional[float]:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), 8)


def _sample_evenly(values: Sequence[_T], limit: int) -> List[_T]:
    """Preserve order while reducing a series deterministically and evenly."""
    if limit <= 0:
        return []
    if len(values) <= limit:
        return list(values)
    if limit == 1:
        return [values[0]]
    last_index = len(values) - 1
    selected = [values[(index * last_index) // (limit - 1)] for index in range(limit)]
    return selected


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def pearson_correlation(left: Sequence[Any], right: Sequence[Any]) -> Optional[float]:
    """Calculate a finite Pearson r from paired numeric values, or ``None``."""
    paired: List[Tuple[float, float]] = []
    for left_value, right_value in zip(left, right):
        x = _coerce_number(left_value)
        y = _coerce_number(right_value)
        if x is not None and y is not None:
            paired.append((x, y))
    if len(paired) < 2:
        return None
    left_values, right_values = zip(*paired)
    left_mean = _mean(left_values)
    right_mean = _mean(right_values)
    numerator = math.fsum((x - left_mean) * (y - right_mean) for x, y in paired)
    left_sum_squares = math.fsum((x - left_mean) ** 2 for x in left_values)
    right_sum_squares = math.fsum((y - right_mean) ** 2 for y in right_values)
    denominator = math.sqrt(left_sum_squares * right_sum_squares)
    if denominator <= _EPSILON:
        return None
    # Floating-point rounding can push an ideal coefficient minutely outside
    # [-1, 1], which is not useful in an API response.
    return max(-1.0, min(1.0, numerator / denominator))


def _average_ranks(values: Sequence[float]) -> List[float]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [0.0] * len(values)
    position = 0
    while position < len(ordered):
        end = position + 1
        while end < len(ordered) and ordered[end][1] == ordered[position][1]:
            end += 1
        # Ranks are one-based by convention; ties receive their average rank.
        average_rank = (position + 1 + end) / 2.0
        for tie_index in range(position, end):
            ranks[ordered[tie_index][0]] = average_rank
        position = end
    return ranks


def spearman_correlation(left: Sequence[Any], right: Sequence[Any]) -> Optional[float]:
    """Calculate Spearman rho using average ranks for ties."""
    paired: List[Tuple[float, float]] = []
    for left_value, right_value in zip(left, right):
        x = _coerce_number(left_value)
        y = _coerce_number(right_value)
        if x is not None and y is not None:
            paired.append((x, y))
    if len(paired) < 2:
        return None
    left_values, right_values = zip(*paired)
    return pearson_correlation(_average_ranks(left_values), _average_ranks(right_values))


def _relationship_strength(coefficient: Optional[float]) -> str:
    if coefficient is None:
        return "not_computable"
    magnitude = abs(coefficient)
    if magnitude < 0.2:
        return "negligible"
    if magnitude < 0.4:
        return "weak"
    if magnitude < 0.6:
        return "moderate"
    if magnitude < 0.8:
        return "strong"
    return "very_strong"


def _association_confidence(
    coefficient: Optional[float],
    observations: int,
    possible_observations: int,
) -> float:
    """Score evidence sufficiency for an *association*, never a causal claim."""
    if coefficient is None or observations < 2:
        return 0.0
    sample_score = min(1.0, math.log10(max(observations, 1)) / math.log10(100.0))
    coverage = min(1.0, observations / max(possible_observations, 1))
    score = 0.50 * abs(coefficient) + 0.30 * sample_score + 0.20 * coverage
    return round(max(0.0, min(1.0, score)), 6)


def causation_guardrail(association_confidence: float) -> Dict[str, Any]:
    """Return an explicit, stable block against causal language.

    A strong correlation and clean lineage improve confidence that an
    *association* is worth investigating.  They cannot identify a causal
    direction or eliminate confounding from observational source files.
    """
    return {
        "status": "not_established",
        "causal_confidence": 0.0,
        "association_confidence": round(max(0.0, min(1.0, association_confidence)), 6),
        "safe_interpretation": "Observed association; investigate, do not infer causation.",
        "blocked_interpretation": "This analysis does not support a claim that one metric caused the other.",
        "required_before_causal_claim": [
            "A pre-specified causal question and causal graph",
            "Control for plausible confounders and selection bias",
            "Temporal ordering at an appropriate operational granularity",
            "An intervention, experiment, or validated quasi-experimental design",
            "Independent review and human approval",
        ],
    }


def lagged_correlation(
    left: Sequence[Any],
    right: Sequence[Any],
    *,
    max_lag_steps: int = 24,
    min_observations: int = 6,
) -> Dict[str, Any]:
    """Calculate correlations at integer sequence offsets.

    Positive ``right_lag_steps`` means the right-hand metric is observed later
    in the supplied chronological sequence.  This is a lead/lag *screen*, not
    evidence of causal direction.
    """
    max_lag_steps = _positive_int(max_lag_steps, 24, minimum=0)
    min_observations = _positive_int(min_observations, 6, minimum=2)
    left_values = [_coerce_number(value) for value in left]
    right_values = [_coerce_number(value) for value in right]
    length = min(len(left_values), len(right_values))
    candidates: List[Dict[str, Any]] = []

    for lag in range(-max_lag_steps, max_lag_steps + 1):
        if lag > 0:
            left_slice = left_values[: length - lag]
            right_slice = right_values[lag:length]
        elif lag < 0:
            left_slice = left_values[-lag:length]
            right_slice = right_values[: length + lag]
        else:
            left_slice = left_values[:length]
            right_slice = right_values[:length]

        paired = [
            (x, y)
            for x, y in zip(left_slice, right_slice)
            if x is not None and y is not None
        ]
        if len(paired) < min_observations:
            continue
        x_values, y_values = zip(*paired)
        coefficient = pearson_correlation(x_values, y_values)
        if coefficient is None:
            continue
        candidates.append(
            {
                "right_lag_steps": lag,
                "observation_count": len(paired),
                "pearson_r": _json_number(coefficient),
            }
        )

    if not candidates:
        return {
            "status": "insufficient_data",
            "definition": "Positive right_lag_steps means the right metric occurs later.",
            "tested_lags": [],
            "best_lag": None,
        }

    # Highest magnitude wins.  Exact ties favour a contemporaneous relation,
    # then the smaller absolute lag, then the earlier right-side measurement.
    best = sorted(
        candidates,
        key=lambda result: (
            -abs(float(result["pearson_r"])),
            -int(result["observation_count"]),
            abs(int(result["right_lag_steps"])),
            int(result["right_lag_steps"]),
        ),
    )[0]
    return {
        "status": "ok",
        "definition": "Positive right_lag_steps means the right metric occurs later.",
        "tested_lags": candidates,
        "best_lag": best,
        "causation_guardrail": (
            "Lead/lag is descriptive and does not establish that either metric caused the other."
        ),
    }


def detect_anomalies(
    values: Sequence[Any],
    *,
    z_threshold: float = 3.5,
    max_anomalies: int = 100,
) -> Dict[str, Any]:
    """Detect robust univariate outliers using median absolute deviation.

    If all normal values are identical, MAD is zero; a standard-deviation
    fallback prevents division by zero while preserving that diagnostic fact in
    the response.
    """
    z_threshold = _positive_float(z_threshold, 3.5, minimum=0.1)
    max_anomalies = _positive_int(max_anomalies, 100)
    numeric_points = [
        (index, numeric)
        for index, value in enumerate(values)
        if (numeric := _coerce_number(value)) is not None
    ]
    if len(numeric_points) < 3:
        return {
            "status": "insufficient_data",
            "method": "robust_mad_zscore",
            "observation_count": len(numeric_points),
            "anomalies": [],
        }

    series = [point[1] for point in numeric_points]
    median = float(statistics.median(series))
    mad = float(statistics.median(abs(value - median) for value in series))
    anomalies: List[Dict[str, Any]] = []
    method = "robust_mad_zscore"
    effective_threshold = z_threshold

    if mad > _EPSILON:
        scale = 1.4826 * mad
        scores = [0.67448975 * (value - median) / mad for value in series]
    else:
        standard_deviation = float(statistics.pstdev(series))
        if standard_deviation <= _EPSILON:
            return {
                "status": "ok",
                "method": "constant_series",
                "observation_count": len(series),
                "baseline": {"median": _json_number(median), "mad": _json_number(mad)},
                "anomalies": [],
            }
        method = "standard_zscore_zero_mad_fallback"
        mean = _mean(series)
        scale = standard_deviation
        scores = [(value - mean) / standard_deviation for value in series]
        # A bounded series with one outlier has a maximum standard z-score of
        # sqrt(n - 1).  The fallback remains conservative, but does not make a
        # clearly isolated point impossible to detect in short spreadsheets.
        effective_threshold = min(z_threshold, 3.0)

    for (source_index, value), score in zip(numeric_points, scores):
        if abs(score) >= effective_threshold:
            anomalies.append(
                {
                    "index": source_index,
                    "value": _json_number(value),
                    "score": _json_number(score),
                    "direction": "high" if score > 0 else "low",
                }
            )
    anomalies.sort(key=lambda anomaly: (-abs(float(anomaly["score"])), anomaly["index"]))
    truncated = len(anomalies) > max_anomalies
    return {
        "status": "ok",
        "method": method,
        "observation_count": len(series),
        "baseline": {
            "median": _json_number(median),
            "mad": _json_number(mad),
            "scale": _json_number(scale),
            "threshold": _json_number(effective_threshold),
        },
        "anomalies": anomalies[:max_anomalies],
        "truncated": truncated,
        "interpretation": "Outliers are review signals, not diagnoses of a root cause.",
    }


def detect_change_points(
    values: Sequence[Any],
    *,
    min_segment_size: int = 6,
    score_threshold: float = 2.5,
) -> Dict[str, Any]:
    """Find the strongest bounded mean-shift candidate in an ordered series.

    This deliberately returns at most one candidate.  Recursive segmentation
    can be useful, but it creates a false sense of certainty when the source
    order is incomplete or operational regimes are not comparable.
    """
    min_segment_size = _positive_int(min_segment_size, 6, minimum=2)
    score_threshold = _positive_float(score_threshold, 2.5, minimum=0.1)
    numeric_points = [
        (index, numeric)
        for index, value in enumerate(values)
        if (numeric := _coerce_number(value)) is not None
    ]
    required = min_segment_size * 2
    if len(numeric_points) < required:
        return {
            "status": "insufficient_data",
            "observation_count": len(numeric_points),
            "minimum_required": required,
            "change_point": None,
        }

    series = [point[1] for point in numeric_points]
    count = len(series)
    prefix_sum = [0.0]
    prefix_sum_squares = [0.0]
    for value in series:
        prefix_sum.append(prefix_sum[-1] + value)
        prefix_sum_squares.append(prefix_sum_squares[-1] + value * value)

    def segment_stats(start: int, end: int) -> Tuple[int, float, float]:
        segment_count = end - start
        total = prefix_sum[end] - prefix_sum[start]
        total_squares = prefix_sum_squares[end] - prefix_sum_squares[start]
        mean = total / segment_count
        variance = max(0.0, total_squares / segment_count - mean * mean)
        return segment_count, mean, variance

    best: Optional[Dict[str, Any]] = None
    for split in range(min_segment_size, count - min_segment_size + 1):
        left_count, left_mean, left_variance = segment_stats(0, split)
        right_count, right_mean, right_variance = segment_stats(split, count)
        delta = right_mean - left_mean
        pooled_standard_deviation = math.sqrt((left_variance + right_variance) / 2.0)
        if pooled_standard_deviation <= _EPSILON:
            score = _MAX_SCORE if abs(delta) > _EPSILON else 0.0
        else:
            score = min(_MAX_SCORE, abs(delta) / pooled_standard_deviation)
        candidate = {
            "index": numeric_points[split][0],
            "left_observation_count": left_count,
            "right_observation_count": right_count,
            "left_mean": _json_number(left_mean),
            "right_mean": _json_number(right_mean),
            "mean_delta": _json_number(delta),
            "effect_size": _json_number(score),
        }
        if best is None or score > float(best["effect_size"]) + _EPSILON:
            best = candidate

    if best is None or float(best["effect_size"]) < score_threshold:
        return {
            "status": "ok",
            "observation_count": count,
            "change_point": None,
            "threshold": _json_number(score_threshold),
            "interpretation": "No mean-shift candidate crossed the review threshold.",
        }
    return {
        "status": "ok",
        "observation_count": count,
        "change_point": best,
        "threshold": _json_number(score_threshold),
        "interpretation": "A mean-shift candidate is a review signal, not an identified operational cause.",
    }


@dataclass(frozen=True)
class _Row:
    source_index: int
    values: Mapping[str, Any]
    event_time: Optional[datetime]


def _select_time_field(rows: Sequence[Mapping[str, Any]], requested: Optional[str]) -> Optional[str]:
    if requested:
        return requested
    counts: Dict[str, int] = {}
    for row in rows:
        for field, value in row.items():
            if _looks_like_time_field(str(field)) and _parse_time(value) is not None:
                counts[str(field)] = counts.get(str(field), 0) + 1
    if not counts:
        return None
    return sorted(counts, key=lambda field: (-counts[field], field))[0]


def _flatten_evidence_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Use the scalar fields payload when given an evidence-engine row."""
    fields = row.get("fields")
    if isinstance(fields, Mapping):
        return fields
    return row


def _metadata_for_point(row: _Row) -> Dict[str, Any]:
    return {
        "source_index": row.source_index,
        "event_time": row.event_time.isoformat() if row.event_time else None,
    }


def _field_series(rows: Sequence[_Row], field: str) -> List[Tuple[_Row, float]]:
    series: List[Tuple[_Row, float]] = []
    for row in rows:
        numeric = _coerce_number(row.values.get(field))
        if numeric is not None:
            series.append((row, numeric))
    return series


def _anomaly_output(series: Sequence[Tuple[_Row, float]], limits: OperationalAnalyticsLimits) -> Dict[str, Any]:
    sampled = _sample_evenly(series, limits.max_series_points)
    base = detect_anomalies(
        [value for _row, value in sampled],
        z_threshold=limits.anomaly_z_threshold,
        max_anomalies=limits.max_anomalies_per_field,
    )
    for anomaly in base.get("anomalies", []):
        sample_index = int(anomaly["index"])
        if 0 <= sample_index < len(sampled):
            anomaly.update(_metadata_for_point(sampled[sample_index][0]))
    base["sampled"] = len(sampled) < len(series)
    base["available_observation_count"] = len(series)
    return base


def _change_output(series: Sequence[Tuple[_Row, float]], limits: OperationalAnalyticsLimits) -> Dict[str, Any]:
    sampled = _sample_evenly(series, limits.max_series_points)
    base = detect_change_points(
        [value for _row, value in sampled],
        min_segment_size=limits.min_change_segment,
        score_threshold=limits.change_score_threshold,
    )
    change_point = base.get("change_point")
    if isinstance(change_point, dict):
        sample_index = int(change_point["index"])
        if 0 <= sample_index < len(sampled):
            change_point.update(_metadata_for_point(sampled[sample_index][0]))
    base["sampled"] = len(sampled) < len(series)
    base["available_observation_count"] = len(series)
    return base


def _relationship_output(
    left_field: str,
    right_field: str,
    rows: Sequence[_Row],
    limits: OperationalAnalyticsLimits,
    *,
    time_ordered: bool,
) -> Dict[str, Any]:
    observations: List[Tuple[_Row, float, float]] = []
    for row in rows:
        left_value = _coerce_number(row.values.get(left_field))
        right_value = _coerce_number(row.values.get(right_field))
        if left_value is not None and right_value is not None:
            observations.append((row, left_value, right_value))
    available_count = len(observations)
    sampled = _sample_evenly(observations, limits.max_series_points)
    left_values = [entry[1] for entry in sampled]
    right_values = [entry[2] for entry in sampled]
    coefficient = pearson_correlation(left_values, right_values)
    spearman = spearman_correlation(left_values, right_values)
    enough_data = len(sampled) >= limits.min_observations
    if not enough_data:
        coefficient = None
        spearman = None
    association_confidence = _association_confidence(
        coefficient,
        len(sampled) if enough_data else 0,
        len(rows),
    )
    result: Dict[str, Any] = {
        "left_field": left_field,
        "right_field": right_field,
        "status": "ok" if enough_data and coefficient is not None else "insufficient_data",
        "available_observation_count": available_count,
        "observation_count": len(sampled),
        "sampled": len(sampled) < available_count,
        "pearson_r": _json_number(coefficient),
        "spearman_rho": _json_number(spearman),
        "direction": (
            "positive" if coefficient and coefficient > 0 else "negative" if coefficient and coefficient < 0 else "none"
        ),
        "strength": _relationship_strength(coefficient),
        "association_confidence": association_confidence,
        "causation": causation_guardrail(association_confidence),
    }
    timed = [entry for entry in sampled if entry[0].event_time is not None]
    if not time_ordered or len(timed) < limits.min_observations:
        result["lag_analysis"] = {
            "status": "not_available",
            "reason": "A parseable time field is required for a lead/lag analysis.",
            "causation_guardrail": "No causal direction is inferred from an unavailable lag analysis.",
        }
    else:
        result["lag_analysis"] = lagged_correlation(
            [entry[1] for entry in timed],
            [entry[2] for entry in timed],
            max_lag_steps=limits.max_lag_steps,
            min_observations=limits.min_observations,
        )
    return result


def analyze_operational_relationships(
    rows: Iterable[Mapping[str, Any]],
    *,
    numeric_fields: Optional[Sequence[str]] = None,
    time_field: Optional[str] = None,
    limits: Optional[OperationalAnalyticsLimits] = None,
) -> Dict[str, Any]:
    """Analyze bounded operational records deterministically.

    ``rows`` may be raw tabular rows or common-evidence rows with a ``fields``
    mapping.  Returned metrics are intended for a review UI and retain source
    row positions for anomalies/change points.  Empty, invalid, and constant
    columns are reported as insufficient rather than fabricated as zero
    correlations.
    """
    effective_limits = _normalised_limits(limits)
    raw_rows: List[Tuple[int, Mapping[str, Any]]] = []
    input_truncated = False
    invalid_row_count = 0
    for source_index, candidate in enumerate(rows):
        # Bound *input consumption*, not merely successfully parsed rows.  A
        # malformed stream must not bypass the row cap by yielding millions of
        # invalid records before its first usable one.
        if source_index >= effective_limits.max_rows:
            input_truncated = True
            break
        if not isinstance(candidate, Mapping):
            invalid_row_count += 1
            continue
        flattened = _flatten_evidence_row(candidate)
        if not isinstance(flattened, Mapping):
            invalid_row_count += 1
            continue
        raw_rows.append((source_index, flattened))

    selected_time_field = _select_time_field([row for _index, row in raw_rows], time_field)
    ordered_rows = [
        _Row(
            source_index=source_index,
            values=row,
            event_time=_parse_time(row.get(selected_time_field)) if selected_time_field else None,
        )
        for source_index, row in raw_rows
    ]
    time_value_count = sum(row.event_time is not None for row in ordered_rows)
    time_ordered = bool(selected_time_field and time_value_count >= effective_limits.min_observations)
    if time_ordered:
        # Rows with an absent timestamp stay last in source order; they can
        # contribute to contemporaneous association but never to lag metrics.
        ordered_rows.sort(
            key=lambda row: (
                row.event_time is None,
                row.event_time or datetime.max.replace(tzinfo=timezone.utc),
                row.source_index,
            )
        )

    numeric_counts: Dict[str, int] = {}
    requested = {str(field) for field in numeric_fields} if numeric_fields else None
    for row in ordered_rows:
        for field, value in row.values.items():
            field_name = str(field)
            if requested is not None and field_name not in requested:
                continue
            if _coerce_number(value) is not None:
                numeric_counts[field_name] = numeric_counts.get(field_name, 0) + 1
    fields = [
        field
        for field in sorted(numeric_counts, key=lambda name: (-numeric_counts[name], name))
        if numeric_counts[field] >= effective_limits.min_observations
    ][: effective_limits.max_numeric_fields]

    relationships: List[Dict[str, Any]] = []
    pair_limit_reached = False
    for pair_index, (left_field, right_field) in enumerate(combinations(sorted(fields), 2)):
        if pair_index >= effective_limits.max_pair_analyses:
            pair_limit_reached = True
            break
        relationships.append(
            _relationship_output(
                left_field,
                right_field,
                ordered_rows,
                effective_limits,
                time_ordered=time_ordered,
            )
        )

    field_signals: Dict[str, Dict[str, Any]] = {}
    for field in fields:
        series = _field_series(ordered_rows, field)
        field_signals[field] = {
            "anomalies": _anomaly_output(series, effective_limits),
            "change_point": _change_output(series, effective_limits),
            "ordering": "event_time" if time_ordered else "source_row_order",
        }

    status = "ok" if relationships or field_signals else "insufficient_data"
    return {
        "status": status,
        "analysis_type": "deterministic_operational_statistics",
        "row_count": len(raw_rows),
        "invalid_row_count": invalid_row_count,
        "time_field": selected_time_field,
        "time_ordered": time_ordered,
        "time_value_count": time_value_count,
        "numeric_fields": fields,
        "relationships": relationships,
        "field_signals": field_signals,
        "limits": {
            "max_rows": effective_limits.max_rows,
            "max_numeric_fields": effective_limits.max_numeric_fields,
            "max_pair_analyses": effective_limits.max_pair_analyses,
            "max_series_points": effective_limits.max_series_points,
            "max_lag_steps": effective_limits.max_lag_steps,
            "min_observations": effective_limits.min_observations,
        },
        "bounded": {
            "input_truncated": input_truncated,
            "pair_limit_reached": pair_limit_reached,
        },
        "causation": causation_guardrail(0.0),
    }


def analyze_evidence_rows(
    evidence_rows: Iterable[Mapping[str, Any]],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Convenience alias for common evidence-table ``evidence_rows`` output."""
    return analyze_operational_relationships(evidence_rows, **kwargs)


__all__ = [
    "OperationalAnalyticsLimits",
    "analyze_evidence_rows",
    "analyze_operational_relationships",
    "causation_guardrail",
    "detect_anomalies",
    "detect_change_points",
    "lagged_correlation",
    "pearson_correlation",
    "spearman_correlation",
]
