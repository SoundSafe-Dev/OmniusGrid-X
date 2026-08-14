"""Deterministic normalization for long-form operational evidence rows.

This module is deliberately dependency-free and has no database or API
coupling.  It is intended for intake code that has already selected one source
row at a time and needs an auditable, conservative common representation.

The normalizer makes only lossless or explicitly declared assumptions:

* Header mapping is alias based; it never fuzzy-matches a business field.
* Unit conversion uses a fixed registry and refuses unknown or incompatible
  dimensions.
* Naive timestamps require an explicit assumed timezone.  Ambiguous and
  nonexistent daylight-saving local times are rejected unless a caller gives a
  ``naive_fold`` for the former.
* Every assumption, warning, conversion, and quality penalty is returned with
  the result so callers can preserve evidence lineage and route rows for
  review.

The service normalizes *long-form* rows (one value and one unit per row).  For
wide source tables, use :func:`suggest_measurement_columns` to identify columns
that should be safely exploded by the intake layer before calling
``normalize_operational_evidence_row``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# These are deliberately small, stable semantic targets.  Callers can supply
# an explicit source-header -> target mapping for a source system whose schema
# does not use one of the conservative aliases below.
CANONICAL_EVIDENCE_FIELDS: Tuple[str, ...] = (
    "record_id",
    "source_id",
    "asset_id",
    "facility_id",
    "line_id",
    "work_order_id",
    "batch_id",
    "shift",
    "event_time",
    "metric_name",
    "value",
    "unit",
)

DEFAULT_REQUIRED_FIELDS: Tuple[str, ...] = (
    "asset_id",
    "event_time",
    "metric_name",
    "value",
)


def normalize_header(value: Any) -> str:
    """Return a deterministic token form suitable for schema alias matching.

    This is intentionally not a semantic matcher.  For example, ``Machine
    Identifier`` and ``Asset ID`` normalize to different values unless an alias
    explicitly relates them.
    """

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = text.casefold().replace("&", " and ")
    return "_".join(re.findall(r"[a-z0-9]+", text))


_FIELD_ALIAS_GROUPS: Mapping[str, Tuple[str, ...]] = {
    "record_id": ("record_id", "id", "row_id", "event_id", "reading_id"),
    "source_id": (
        "source_id",
        "source",
        "source_system",
        "origin",
        "system",
        "provider",
    ),
    "asset_id": (
        "asset_id",
        "asset",
        "asset_number",
        "machine_id",
        "machine",
        "machine_number",
        "equipment_id",
        "equipment",
        "equipment_number",
        "device_id",
        "device",
    ),
    "facility_id": (
        "facility_id",
        "facility",
        "facility_code",
        "plant_id",
        "plant",
        "site_id",
        "site",
        "location_id",
    ),
    "line_id": (
        "line_id",
        "line",
        "production_line",
        "production_line_id",
        "line_number",
    ),
    "work_order_id": (
        "work_order_id",
        "work_order",
        "work_order_number",
        "wo_number",
        "wo_id",
    ),
    "batch_id": ("batch_id", "batch", "batch_number", "lot_id", "lot", "lot_number"),
    "shift": ("shift", "shift_name", "shift_code"),
    "event_time": (
        "event_time",
        "event_timestamp",
        "timestamp",
        "timestamp_utc",
        "recorded_at",
        "observed_at",
        "measurement_time",
        "datetime",
        "date_time",
        "date",
        "time",
    ),
    "metric_name": (
        "metric_name",
        "metric",
        "measurement_name",
        "measurement",
        "tag_name",
        "tag",
        "signal",
        "parameter",
        "variable",
    ),
    "value": (
        "value",
        "reading",
        "reading_value",
        "measurement_value",
        "metric_value",
        "observed_value",
        "quantity",
        "amount",
    ),
    "unit": ("unit", "units", "uom", "unit_of_measure", "measurement_unit"),
}

_FIELD_ALIASES: Dict[str, str] = {
    normalize_header(alias): canonical
    for canonical, aliases in _FIELD_ALIAS_GROUPS.items()
    for alias in aliases
}


@dataclass(frozen=True)
class NormalizationIssue:
    """One stable, machine-readable normalization or quality finding."""

    code: str
    severity: str
    field: Optional[str]
    message: str
    penalty: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
            "penalty": self.penalty,
        }


@dataclass(frozen=True)
class UnitDetection:
    """The result of recognizing a unit token or a value-column header."""

    recognized: bool
    raw_unit: Optional[str]
    unit: Optional[str]
    dimension: Optional[str]
    source: Optional[str]
    warning_codes: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "recognized": self.recognized,
            "raw_unit": self.raw_unit,
            "unit": self.unit,
            "dimension": self.dimension,
            "source": self.source,
            "warning_codes": list(self.warning_codes),
        }


@dataclass(frozen=True)
class ConversionResult:
    """A safe unit conversion, or the reason no conversion was performed."""

    success: bool
    input_value: Any
    value: Optional[Any]
    from_unit: Optional[str]
    to_unit: Optional[str]
    dimension: Optional[str]
    reason_code: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "input_value": _json_safe(self.input_value),
            "value": _json_safe(self.value),
            "from_unit": self.from_unit,
            "to_unit": self.to_unit,
            "dimension": self.dimension,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class TimestampNormalization:
    """The UTC timestamp and any explicit timezone assumption made."""

    success: bool
    input_value: Any
    canonical_timestamp: Optional[str]
    source_timezone: Optional[str]
    timezone_assumption: Optional[str]
    warning_codes: Tuple[str, ...] = ()
    error_code: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "input_value": _json_safe(self.input_value),
            "canonical_timestamp": self.canonical_timestamp,
            "source_timezone": self.source_timezone,
            "timezone_assumption": self.timezone_assumption,
            "warning_codes": list(self.warning_codes),
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class DataQualityReport:
    """Deterministic data-quality outcome for one normalized row."""

    score: int
    grade: str
    disposition: str
    valid: bool
    review_required: bool
    required_fields: Tuple[str, ...]
    present_required_fields: Tuple[str, ...]
    missing_required_fields: Tuple[str, ...]
    issues: Tuple[NormalizationIssue, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "grade": self.grade,
            "disposition": self.disposition,
            "valid": self.valid,
            "review_required": self.review_required,
            "required_fields": list(self.required_fields),
            "present_required_fields": list(self.present_required_fields),
            "missing_required_fields": list(self.missing_required_fields),
            "issues": [issue.as_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class NormalizedEvidenceRow:
    """Auditable result of normalizing one operational evidence row."""

    normalized_row: Mapping[str, Any]
    schema_mapping: Mapping[str, Any]
    conversions: Tuple[ConversionResult, ...]
    timestamp: TimestampNormalization
    quality: DataQualityReport
    unmapped_fields: Mapping[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "normalized_row": _json_safe(dict(self.normalized_row)),
            "schema_mapping": _json_safe(dict(self.schema_mapping)),
            "conversions": [conversion.as_dict() for conversion in self.conversions],
            "timestamp": self.timestamp.as_dict(),
            "quality": self.quality.as_dict(),
            "unmapped_fields": _json_safe(dict(self.unmapped_fields)),
        }


@dataclass(frozen=True)
class _UnitSpec:
    label: str
    dimension: str
    factor_to_canonical: Decimal
    offset_to_canonical: Decimal = Decimal("0")


_CANONICAL_UNIT_BY_DIMENSION = {
    "temperature": "degC",
    "length": "m",
    "mass": "kg",
    "energy": "kWh",
    "pressure": "kPa",
}


def _decimal(value: str) -> Decimal:
    return Decimal(value)


# Conversion is canonical_value = input_value * factor + offset.  Decimal
# constants prevent source-platform float rounding from changing an audit trail.
_UNIT_SPECS: Dict[str, _UnitSpec] = {
    # Temperature -> degC
    "degC": _UnitSpec("degC", "temperature", _decimal("1")),
    "degF": _UnitSpec(
        "degF", "temperature", _decimal("0.5555555555555555555555555556"),
        _decimal("-17.77777777777777777777777778"),
    ),
    "K": _UnitSpec("K", "temperature", _decimal("1"), _decimal("-273.15")),
    # Length -> m
    "m": _UnitSpec("m", "length", _decimal("1")),
    "km": _UnitSpec("km", "length", _decimal("1000")),
    "cm": _UnitSpec("cm", "length", _decimal("0.01")),
    "mm": _UnitSpec("mm", "length", _decimal("0.001")),
    "um": _UnitSpec("um", "length", _decimal("0.000001")),
    "in": _UnitSpec("in", "length", _decimal("0.0254")),
    "ft": _UnitSpec("ft", "length", _decimal("0.3048")),
    "yd": _UnitSpec("yd", "length", _decimal("0.9144")),
    "mi": _UnitSpec("mi", "length", _decimal("1609.344")),
    # Mass -> kg
    "kg": _UnitSpec("kg", "mass", _decimal("1")),
    "g": _UnitSpec("g", "mass", _decimal("0.001")),
    "mg": _UnitSpec("mg", "mass", _decimal("0.000001")),
    "tonne": _UnitSpec("tonne", "mass", _decimal("1000")),
    "lb": _UnitSpec("lb", "mass", _decimal("0.45359237")),
    "oz": _UnitSpec("oz", "mass", _decimal("0.028349523125")),
    # Energy -> kWh
    "Wh": _UnitSpec("Wh", "energy", _decimal("0.001")),
    "kWh": _UnitSpec("kWh", "energy", _decimal("1")),
    "MWh": _UnitSpec("MWh", "energy", _decimal("1000")),
    "GWh": _UnitSpec("GWh", "energy", _decimal("1000000")),
    "J": _UnitSpec("J", "energy", _decimal("0.0000002777777777777777777778")),
    "kJ": _UnitSpec("kJ", "energy", _decimal("0.0002777777777777777777777778")),
    "MJ": _UnitSpec("MJ", "energy", _decimal("0.2777777777777777777777778")),
    "GJ": _UnitSpec("GJ", "energy", _decimal("277.7777777777777777777777778")),
    # Pressure -> kPa
    "Pa": _UnitSpec("Pa", "pressure", _decimal("0.001")),
    "hPa": _UnitSpec("hPa", "pressure", _decimal("0.1")),
    "kPa": _UnitSpec("kPa", "pressure", _decimal("1")),
    "MPa": _UnitSpec("MPa", "pressure", _decimal("1000")),
    "bar": _UnitSpec("bar", "pressure", _decimal("100")),
    "mbar": _UnitSpec("mbar", "pressure", _decimal("0.1")),
    "psi": _UnitSpec("psi", "pressure", _decimal("6.894757293168361")),
    "atm": _UnitSpec("atm", "pressure", _decimal("101.325")),
    "torr": _UnitSpec("torr", "pressure", _decimal("0.1333223684210526315789473684")),
    "mmHg": _UnitSpec("mmHg", "pressure", _decimal("0.133322387415")),
}


def _normalize_unit_token(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = text.replace("°", "deg").replace("µ", "u").replace("μ", "u")
    text = text.replace("³", "3").replace("²", "2")
    return "".join(ch for ch in text.casefold() if ch.isalnum())


_UNIT_ALIASES: Dict[str, str] = {}


def _register_unit_aliases(label: str, *aliases: str) -> None:
    for alias in (label,) + aliases:
        _UNIT_ALIASES[_normalize_unit_token(alias)] = label


_register_unit_aliases("degC", "c", "celsius", "degree_celsius", "degrees_celsius")
_register_unit_aliases("degF", "f", "fahrenheit", "degree_fahrenheit", "degrees_fahrenheit")
_register_unit_aliases("K", "kelvin")
_register_unit_aliases("m", "meter", "meters", "metre", "metres")
_register_unit_aliases("km", "kilometer", "kilometers", "kilometre", "kilometres")
_register_unit_aliases("cm", "centimeter", "centimeters", "centimetre", "centimetres")
_register_unit_aliases("mm", "millimeter", "millimeters", "millimetre", "millimetres")
_register_unit_aliases("um", "micrometer", "micrometers", "micrometre", "micrometres", "micron")
_register_unit_aliases("in", "inch", "inches")
_register_unit_aliases("ft", "foot", "feet")
_register_unit_aliases("yd", "yard", "yards")
_register_unit_aliases("mi", "mile", "miles")
_register_unit_aliases("kg", "kilogram", "kilograms")
_register_unit_aliases("g", "gram", "grams")
_register_unit_aliases("mg", "milligram", "milligrams")
_register_unit_aliases("tonne", "tonnes", "metric_ton", "metric_tonne")
_register_unit_aliases("lb", "lbs", "pound", "pounds")
_register_unit_aliases("oz", "ounce", "ounces")
_register_unit_aliases("Wh", "watt_hour", "watt_hours")
_register_unit_aliases("kWh", "kilowatt_hour", "kilowatt_hours")
_register_unit_aliases("MWh", "megawatt_hour", "megawatt_hours")
_register_unit_aliases("GWh", "gigawatt_hour", "gigawatt_hours")
_register_unit_aliases("J", "joule", "joules")
_register_unit_aliases("kJ", "kilojoule", "kilojoules")
_register_unit_aliases("MJ", "megajoule", "megajoules")
_register_unit_aliases("GJ", "gigajoule", "gigajoules")
_register_unit_aliases("Pa", "pascal", "pascals")
_register_unit_aliases("hPa", "hectopascal", "hectopascals")
_register_unit_aliases("kPa", "kilopascal", "kilopascals")
_register_unit_aliases("MPa", "megapascal", "megapascals")
_register_unit_aliases("bar", "bars")
_register_unit_aliases("mbar", "millibar", "millibars")
_register_unit_aliases("psi", "pounds_per_square_inch")
_register_unit_aliases("atm", "atmosphere", "atmospheres")
_register_unit_aliases("torr")
_register_unit_aliases("mmHg", "millimetres_of_mercury", "millimeters_of_mercury")


_ISSUE_PENALTIES: Mapping[str, int] = {
    "missing_required_field": 20,
    "invalid_timestamp": 25,
    "invalid_timestamp_type": 25,
    "naive_timestamp_without_timezone": 25,
    "invalid_assumed_timezone": 25,
    "ambiguous_local_time": 25,
    "nonexistent_local_time": 25,
    "epoch_unit_required": 25,
    "invalid_epoch_unit": 25,
    "epoch_precision_exceeds_microseconds": 25,
    "epoch_out_of_range": 25,
    "invalid_numeric_value": 25,
    "unknown_unit": 10,
    "ambiguous_header_unit": 15,
    "unit_conflict": 25,
    "incompatible_unit_dimension": 25,
    "invalid_target_unit": 25,
    "duplicate_mapped_field": 3,
    "conflicting_mapped_fields": 20,
    "invalid_schema_mapping": 10,
    "mapping_source_missing": 3,
    "naive_timestamp_assumed_timezone": 5,
    "date_only_timestamp_assumed_midnight": 5,
    "ambiguous_local_time_resolved": 8,
}

_REVIEW_WARNING_CODES = {
    "unknown_unit",
    "ambiguous_header_unit",
    "unit_conflict",
    "conflicting_mapped_fields",
    "naive_timestamp_assumed_timezone",
    "date_only_timestamp_assumed_midnight",
    "ambiguous_local_time_resolved",
}


def _issue(code: str, severity: str, field: Optional[str], message: str) -> NormalizationIssue:
    return NormalizationIssue(
        code=code,
        severity=severity,
        field=field,
        message=message,
        penalty=_ISSUE_PENALTIES.get(code, 0),
    )


def _json_safe(value: Any) -> Any:
    """Return JSON-safe values without importing a serialization dependency."""

    if isinstance(value, Decimal):
        return _decimal_to_output(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Decimal):
        return not value.is_finite()
    return False


def _decimal_to_output(value: Decimal) -> Any:
    """Preserve whole numbers where possible while keeping output JSON-friendly."""

    if value == value.to_integral_value():
        return int(value)
    numeric = float(value)
    if not math.isfinite(numeric):
        # A Decimal beyond JSON's numeric range is not a useful normalized
        # measurement.  Returning its exact string avoids silently emitting inf.
        return format(value, "f")
    return numeric


def _to_decimal(value: Any) -> Optional[Decimal]:
    if isinstance(value, bool) or _is_missing(value):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value)) if math.isfinite(value) else None
    if isinstance(value, str):
        # Locale-specific separators are deliberately not interpreted.  A caller
        # must parse them using a declared source locale before normalization.
        stripped = value.strip()
        if not stripped or "," in stripped:
            return None
        try:
            parsed = Decimal(stripped)
        except InvalidOperation:
            return None
        return parsed if parsed.is_finite() else None
    return None


def _canonical_field_name(value: Any) -> Optional[str]:
    normalized = normalize_header(value)
    if normalized in CANONICAL_EVIDENCE_FIELDS:
        return normalized
    return _FIELD_ALIASES.get(normalized)


def suggest_schema_mapping(
    headers: Iterable[Any],
    *,
    aliases: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Return conservative header-to-canonical-field mapping suggestions.

    ``aliases`` accepts exact source-header aliases as ``{source: target}`` and
    is useful for an integration-owned mapping registry.  Suggestions apply only
    exact normalized aliases; unrecognized headers are surfaced, not guessed.
    """

    alias_lookup = dict(_FIELD_ALIASES)
    invalid_custom_aliases: List[Dict[str, str]] = []
    if aliases:
        for source, target in aliases.items():
            canonical = _canonical_field_name(target)
            if canonical is None:
                invalid_custom_aliases.append({"source": str(source), "target": str(target)})
                continue
            alias_lookup[normalize_header(source)] = canonical

    suggestions: List[Dict[str, Any]] = []
    suggested_mapping: Dict[str, str] = {}
    by_target: Dict[str, List[str]] = {}
    seen_headers = set()
    for header in sorted((str(header) for header in headers), key=lambda item: (normalize_header(item), item)):
        # A mapping cannot carry two equal keys, but accepting a generic iterable
        # makes duplicate headers possible.  Keep the report deterministic.
        if header in seen_headers:
            continue
        seen_headers.add(header)
        normalized = normalize_header(header)
        canonical = alias_lookup.get(normalized)
        suggestion = {
            "source_header": header,
            "normalized_header": normalized,
            "canonical_field": canonical,
            "confidence": "exact_alias" if canonical else "none",
            "safe_to_apply": bool(canonical),
        }
        suggestions.append(suggestion)
        if canonical:
            suggested_mapping[header] = canonical
            by_target.setdefault(canonical, []).append(header)

    collisions = [
        {"canonical_field": target, "source_headers": sorted(source_headers)}
        for target, source_headers in sorted(by_target.items())
        if len(source_headers) > 1
    ]
    return {
        "suggestions": suggestions,
        "suggested_mapping": suggested_mapping,
        "unmapped_headers": [
            item["source_header"] for item in suggestions if item["canonical_field"] is None
        ],
        "collisions": collisions,
        "invalid_custom_aliases": invalid_custom_aliases,
    }


def _header_unit_candidates(field_name: Any) -> List[UnitDetection]:
    """Extract only explicit suffix/bracket unit declarations from a header."""

    text = str(field_name or "").strip()
    if not text:
        return []

    candidates: List[UnitDetection] = []
    # Parentheses and brackets are the least ambiguous way source schemas state
    # units: ``Temperature (deg F)`` / ``pressure [psi]``.
    for match in re.finditer(r"[\[(]([^\]\)]+)[\])]", text):
        content = match.group(1).strip()
        # A slash in a bracket declaration is a list of possible units, not a
        # compound unit supported by this registry.  Preserve that ambiguity.
        fragments = [piece.strip() for piece in content.split("/") if piece.strip()]
        if len(fragments) > 1:
            fragment_detections = [detect_unit(piece) for piece in fragments]
            recognized = [item for item in fragment_detections if item.recognized]
            if len(recognized) > 1:
                return [
                    UnitDetection(
                        recognized=False,
                        raw_unit=None,
                        unit=None,
                        dimension=None,
                        source="header",
                        warning_codes=("ambiguous_header_unit",),
                    )
                ]
        detection = detect_unit(content)
        if detection.recognized:
            candidates.append(
                UnitDetection(
                    recognized=True,
                    raw_unit=content,
                    unit=detection.unit,
                    dimension=detection.dimension,
                    source="header",
                )
            )

    if candidates:
        return candidates

    # Support conventional suffixes such as temperature_f, flow-kPa, and
    # energy kWh.  Only the final token is interpreted, so identifiers like
    # ``asset_mx_101`` do not get a spurious unit from an earlier token.
    suffixes = [part for part in re.split(r"[\s_\-]+", text) if part]
    if suffixes:
        detection = detect_unit(suffixes[-1])
        if detection.recognized:
            candidates.append(
                UnitDetection(
                    recognized=True,
                    raw_unit=suffixes[-1],
                    unit=detection.unit,
                    dimension=detection.dimension,
                    source="header",
                )
            )
    return candidates


def detect_unit(raw_unit: Any = None, *, field_name: Any = None) -> UnitDetection:
    """Recognize a known unit from an explicit value or an explicit header cue.

    An explicit but unknown ``raw_unit`` is never replaced with a header hint.
    That prevents a typo in a source unit cell from silently changing a reading's
    meaning.
    """

    if not _is_missing(raw_unit):
        raw_text = str(raw_unit).strip()
        label = _UNIT_ALIASES.get(_normalize_unit_token(raw_text))
        if label is None:
            return UnitDetection(
                recognized=False,
                raw_unit=raw_text,
                unit=None,
                dimension=None,
                source="explicit",
                warning_codes=("unknown_unit",),
            )
        spec = _UNIT_SPECS[label]
        return UnitDetection(True, raw_text, spec.label, spec.dimension, "explicit")

    if field_name is None:
        return UnitDetection(False, None, None, None, None)

    candidates = _header_unit_candidates(field_name)
    if not candidates:
        return UnitDetection(False, None, None, None, "header")
    if any("ambiguous_header_unit" in item.warning_codes for item in candidates):
        return UnitDetection(
            False,
            None,
            None,
            None,
            "header",
            warning_codes=("ambiguous_header_unit",),
        )
    unique = {(item.unit, item.dimension) for item in candidates if item.recognized}
    if len(unique) != 1:
        return UnitDetection(
            False,
            None,
            None,
            None,
            "header",
            warning_codes=("ambiguous_header_unit",),
        )
    return candidates[0]


def _metric_name_from_header(header: Any, detected_unit: UnitDetection) -> Optional[str]:
    text = str(header or "")
    text = re.sub(r"[\[(][^\]\)]+[\])]", "", text)
    normalized = normalize_header(text)
    if not normalized:
        return None
    unit_token = normalize_header(detected_unit.raw_unit or detected_unit.unit or "")
    if unit_token and normalized.endswith("_" + unit_token):
        normalized = normalized[: -(len(unit_token) + 1)]
    elif unit_token and normalized == unit_token:
        return None
    return normalized or None


def suggest_measurement_columns(headers: Iterable[Any]) -> List[Dict[str, Any]]:
    """Identify explicit-unit wide columns that can be safely exploded to rows.

    The function only proposes columns such as ``Temperature (deg F)`` or
    ``energy_kwh``.  It does not infer a unit from a metric name alone.
    """

    suggestions: List[Dict[str, Any]] = []
    for header in sorted((str(header) for header in headers), key=lambda item: (normalize_header(item), item)):
        if _canonical_field_name(header) is not None:
            continue
        detection = detect_unit(field_name=header)
        if not detection.recognized:
            continue
        metric_name = _metric_name_from_header(header, detection)
        if metric_name is None:
            continue
        suggestions.append(
            {
                "source_header": header,
                "metric_name": metric_name,
                "unit": detection.unit,
                "dimension": detection.dimension,
                "confidence": "explicit_header_unit",
            }
        )
    return suggestions


def convert_value(value: Any, from_unit: Any, to_unit: Any = None) -> ConversionResult:
    """Convert a measurement only when both units are known and compatible.

    If ``to_unit`` is omitted, the dimension's canonical unit is used.  Unknown,
    incompatible, and non-numeric inputs return ``success=False``; callers must
    keep the source value rather than treating a failed conversion as a zero.
    """

    source = detect_unit(from_unit)
    if not source.recognized:
        return ConversionResult(False, value, None, None, None, None, "unknown_unit")

    if to_unit is None:
        target_label = _CANONICAL_UNIT_BY_DIMENSION[source.dimension or ""]
        target = detect_unit(target_label)
    else:
        target = detect_unit(to_unit)
    if not target.recognized:
        return ConversionResult(
            False,
            value,
            None,
            source.unit,
            None,
            source.dimension,
            "invalid_target_unit",
        )
    if source.dimension != target.dimension:
        return ConversionResult(
            False,
            value,
            None,
            source.unit,
            target.unit,
            source.dimension,
            "incompatible_unit_dimension",
        )

    numeric = _to_decimal(value)
    if numeric is None:
        return ConversionResult(
            False,
            value,
            None,
            source.unit,
            target.unit,
            source.dimension,
            "invalid_numeric_value",
        )

    source_spec = _UNIT_SPECS[source.unit or ""]
    target_spec = _UNIT_SPECS[target.unit or ""]
    canonical = numeric * source_spec.factor_to_canonical + source_spec.offset_to_canonical
    converted = (canonical - target_spec.offset_to_canonical) / target_spec.factor_to_canonical
    return ConversionResult(
        True,
        value,
        _decimal_to_output(converted),
        source.unit,
        target.unit,
        source.dimension,
    )


def _timezone_label(value: tzinfo) -> str:
    if isinstance(value, ZoneInfo):
        return value.key
    if value is timezone.utc:
        return "UTC"
    name = value.tzname(None)
    return name or str(value)


def _resolve_timezone(value: Any) -> Tuple[Optional[tzinfo], Optional[str], Optional[str]]:
    if value is None:
        return None, None, None
    if isinstance(value, str):
        if value.strip().upper() in {"UTC", "Z"}:
            return timezone.utc, "UTC", None
        try:
            zone = ZoneInfo(value.strip())
        except (ZoneInfoNotFoundError, ValueError):
            return None, None, "invalid_assumed_timezone"
        return zone, zone.key, None
    if isinstance(value, tzinfo):
        return value, _timezone_label(value), None
    return None, None, "invalid_assumed_timezone"


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _aware_timezone_label(value: datetime) -> str:
    if isinstance(value.tzinfo, ZoneInfo):
        return value.tzinfo.key
    offset = value.utcoffset()
    if offset == timedelta(0):
        return "UTC"
    label = value.tzname()
    return label or str(offset)


def _localize_naive(
    value: datetime,
    assumed_timezone: Any,
    naive_fold: Optional[int],
    *,
    date_only: bool,
    input_value: Any,
) -> TimestampNormalization:
    zone, label, error_code = _resolve_timezone(assumed_timezone)
    if zone is None:
        return TimestampNormalization(
            False,
            input_value,
            None,
            None,
            None,
            error_code or "naive_timestamp_without_timezone",
        )
    if naive_fold not in (None, 0, 1):
        return TimestampNormalization(False, input_value, None, None, None, (), "invalid_timestamp")

    warning_codes: List[str] = ["naive_timestamp_assumed_timezone"]
    if date_only:
        warning_codes.append("date_only_timestamp_assumed_midnight")

    # ZoneInfo exposes DST ambiguity through fold.  Round-tripping candidate
    # folds through UTC distinguishes an ambiguous local time from one that did
    # not occur when clocks jumped forward.
    if isinstance(zone, ZoneInfo):
        candidates: List[Tuple[int, datetime]] = []
        for fold in (0, 1):
            candidate = value.replace(tzinfo=zone, fold=fold)
            returned = candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
            if returned == value:
                candidates.append((fold, candidate))
        if not candidates:
            return TimestampNormalization(
                False,
                input_value,
                None,
                label,
                None,
                tuple(warning_codes),
                "nonexistent_local_time",
            )
        distinct_offsets = {candidate.utcoffset() for _, candidate in candidates}
        if len(candidates) > 1 and len(distinct_offsets) > 1:
            if naive_fold is None:
                return TimestampNormalization(
                    False,
                    input_value,
                    None,
                    label,
                    None,
                    tuple(warning_codes),
                    "ambiguous_local_time",
                )
            chosen = next(candidate for fold, candidate in candidates if fold == naive_fold)
            warning_codes.append("ambiguous_local_time_resolved")
        else:
            chosen = candidates[0][1]
    else:
        # A fixed-offset tzinfo has no DST ambiguity.  A custom tzinfo cannot be
        # audited as fully as ZoneInfo, but the caller supplied it explicitly.
        chosen = value.replace(tzinfo=zone, fold=naive_fold or 0)

    assumption = "naive timestamp interpreted in {}".format(label)
    return TimestampNormalization(
        True,
        input_value,
        _format_utc(chosen),
        label,
        assumption,
        tuple(warning_codes),
    )


_EPOCH_SCALES_TO_MICROSECONDS = {
    "s": Decimal("1000000"),
    "second": Decimal("1000000"),
    "seconds": Decimal("1000000"),
    "ms": Decimal("1000"),
    "millisecond": Decimal("1000"),
    "milliseconds": Decimal("1000"),
    "us": Decimal("1"),
    "microsecond": Decimal("1"),
    "microseconds": Decimal("1"),
}


def canonicalize_timestamp(
    value: Any,
    *,
    assumed_timezone: Any = "UTC",
    naive_fold: Optional[int] = None,
    epoch_unit: Optional[str] = None,
) -> TimestampNormalization:
    """Canonicalize an ISO/datetime timestamp to UTC with audit metadata.

    Numeric epochs are accepted only with an explicit ``epoch_unit`` so a value
    such as ``1700000000`` is never guessed as seconds versus milliseconds.
    """

    if _is_missing(value):
        return TimestampNormalization(False, value, None, None, None, (), "invalid_timestamp")

    if isinstance(value, datetime):
        parsed = value
        date_only = False
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
        date_only = True
    elif isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        if epoch_unit is None:
            return TimestampNormalization(False, value, None, None, None, (), "epoch_unit_required")
        scale = _EPOCH_SCALES_TO_MICROSECONDS.get(str(epoch_unit).strip().casefold())
        if scale is None:
            return TimestampNormalization(False, value, None, None, None, (), "invalid_epoch_unit")
        numeric = _to_decimal(value)
        if numeric is None:
            return TimestampNormalization(False, value, None, None, None, (), "invalid_timestamp")
        microseconds = numeric * scale
        if microseconds != microseconds.to_integral_value():
            return TimestampNormalization(
                False,
                value,
                None,
                None,
                None,
                (),
                "epoch_precision_exceeds_microseconds",
            )
        try:
            parsed = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
                microseconds=int(microseconds)
            )
        except OverflowError:
            return TimestampNormalization(False, value, None, None, None, (), "epoch_out_of_range")
        return TimestampNormalization(
            True,
            value,
            _format_utc(parsed),
            "UTC",
            "numeric epoch interpreted as {}".format(epoch_unit),
        )
    elif isinstance(value, str):
        text = value.strip()
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                parsed = datetime.combine(date.fromisoformat(text), time.min)
                date_only = True
            else:
                parsed = datetime.fromisoformat(re.sub(r"[zZ]$", "+00:00", text))
                date_only = False
        except ValueError:
            return TimestampNormalization(False, value, None, None, None, (), "invalid_timestamp")
    else:
        return TimestampNormalization(False, value, None, None, None, (), "invalid_timestamp_type")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return _localize_naive(
            parsed,
            assumed_timezone,
            naive_fold,
            date_only=date_only,
            input_value=value,
        )
    return TimestampNormalization(
        True,
        value,
        _format_utc(parsed),
        _aware_timezone_label(parsed),
        None,
    )


def _dedupe_issues(issues: Iterable[NormalizationIssue]) -> Tuple[NormalizationIssue, ...]:
    seen = set()
    deduped: List[NormalizationIssue] = []
    for issue in issues:
        key = (issue.code, issue.severity, issue.field, issue.message)
        if key not in seen:
            seen.add(key)
            deduped.append(issue)
    return tuple(deduped)


def score_data_quality(
    normalized_row: Mapping[str, Any],
    issues: Iterable[NormalizationIssue] = (),
    *,
    required_fields: Sequence[str] = DEFAULT_REQUIRED_FIELDS,
) -> DataQualityReport:
    """Score one row from a fixed 100-point, explainable penalty model."""

    present = tuple(field for field in required_fields if not _is_missing(normalized_row.get(field)))
    missing = tuple(field for field in required_fields if field not in present)
    complete_issues = list(issues)
    existing_missing = {issue.field for issue in complete_issues if issue.code == "missing_required_field"}
    for field in missing:
        if field not in existing_missing:
            complete_issues.append(
                _issue("missing_required_field", "error", field, "Required field is missing.")
            )
    final_issues = _dedupe_issues(complete_issues)
    score = max(0, 100 - sum(issue.penalty for issue in final_issues))
    has_error = any(issue.severity == "error" for issue in final_issues)
    review_required = has_error or any(
        issue.code in _REVIEW_WARNING_CODES for issue in final_issues
    ) or score < 80
    if has_error:
        disposition = "reject"
    elif review_required:
        disposition = "review"
    else:
        disposition = "accept"
    if score >= 95:
        grade = "excellent"
    elif score >= 80:
        grade = "good"
    elif score >= 60:
        grade = "review"
    else:
        grade = "poor"
    return DataQualityReport(
        score=score,
        grade=grade,
        disposition=disposition,
        valid=not has_error,
        review_required=review_required,
        required_fields=tuple(required_fields),
        present_required_fields=present,
        missing_required_fields=missing,
        issues=final_issues,
    )


def _text_value(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _values_identical(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    try:
        return bool(left == right)
    except (TypeError, ValueError):
        return False


def _issue_for_timestamp(result: TimestampNormalization) -> List[NormalizationIssue]:
    issues: List[NormalizationIssue] = []
    if result.error_code:
        issues.append(
            _issue(result.error_code, "error", "event_time", "Timestamp could not be canonicalized.")
        )
    for code in result.warning_codes:
        issues.append(
            _issue(code, "warning", "event_time", "Timestamp used an explicit assumption."))
    return issues


def _prepare_mapping(
    row: Mapping[str, Any], field_mapping: Optional[Mapping[str, str]]
) -> Tuple[Dict[str, str], Dict[str, Any], List[NormalizationIssue]]:
    raw_headers = [str(header) for header in row.keys()]
    aids = suggest_schema_mapping(raw_headers)
    resolved = dict(aids["suggested_mapping"])
    issues: List[NormalizationIssue] = []
    if not field_mapping:
        return resolved, aids, issues

    available_headers = set(raw_headers)
    for source, target in sorted(field_mapping.items(), key=lambda item: (str(item[0]), str(item[1]))):
        source_text = str(source)
        canonical = _canonical_field_name(target)
        if canonical is None:
            issues.append(
                _issue(
                    "invalid_schema_mapping",
                    "warning",
                    source_text,
                    "Explicit mapping target is not a supported canonical field.",
                )
            )
            continue
        if source_text not in available_headers:
            issues.append(
                _issue(
                    "mapping_source_missing",
                    "warning",
                    source_text,
                    "Explicit mapping source header was not present in the row.",
                )
            )
            continue
        resolved[source_text] = canonical
    aids = dict(aids)
    aids["explicit_mapping"] = {str(key): str(value) for key, value in field_mapping.items()}
    return resolved, aids, issues


def normalize_operational_evidence_row(
    row: Mapping[str, Any],
    *,
    field_mapping: Optional[Mapping[str, str]] = None,
    assumed_timezone: Any = "UTC",
    naive_fold: Optional[int] = None,
    epoch_unit: Optional[str] = None,
    required_fields: Sequence[str] = DEFAULT_REQUIRED_FIELDS,
) -> NormalizedEvidenceRow:
    """Normalize one operational row without changing source data in place.

    ``field_mapping`` is an optional ``{source_header: canonical_field}``
    override.  It is intentionally one-way so an ambiguous mapping direction
    cannot alter evidence.  ``assumed_timezone`` is used only for naive/date-only
    values and is always recorded in the timestamp metadata.
    """

    if not isinstance(row, Mapping):
        raise TypeError("row must be a mapping of source headers to values")

    source_items = sorted(
        ((str(header), value) for header, value in row.items()),
        key=lambda item: (normalize_header(item[0]), item[0]),
    )
    resolved_mapping, mapping_aids, issues = _prepare_mapping(row, field_mapping)
    grouped: Dict[str, List[Tuple[str, Any]]] = {}
    unmapped_fields: Dict[str, Any] = {}
    for header, value in source_items:
        canonical = resolved_mapping.get(header)
        if canonical is None:
            unmapped_fields[header] = value
        else:
            grouped.setdefault(canonical, []).append((header, value))

    normalized: Dict[str, Any] = {}
    selected_headers: Dict[str, str] = {}
    for canonical in sorted(grouped):
        candidates = grouped[canonical]
        populated = [(header, value) for header, value in candidates if not _is_missing(value)]
        if not populated:
            normalized[canonical] = None
            continue
        selected_header, selected_value = populated[0]
        if len(populated) > 1:
            values = [value for _, value in populated]
            if all(_values_identical(values[0], value) for value in values[1:]):
                issues.append(
                    _issue(
                        "duplicate_mapped_field",
                        "warning",
                        canonical,
                        "Multiple source headers mapped to the same identical value.",
                    )
                )
            else:
                issues.append(
                    _issue(
                        "conflicting_mapped_fields",
                        "error",
                        canonical,
                        "Multiple source headers mapped to different values.",
                    )
                )
                normalized[canonical] = None
                continue
        normalized[canonical] = selected_value
        selected_headers[canonical] = selected_header

    for field in (
        "record_id",
        "source_id",
        "asset_id",
        "facility_id",
        "line_id",
        "work_order_id",
        "batch_id",
        "shift",
        "metric_name",
        "unit",
    ):
        if field in normalized:
            normalized[field] = _text_value(normalized[field])

    raw_timestamp = normalized.get("event_time")
    if _is_missing(raw_timestamp):
        timestamp_result = TimestampNormalization(False, raw_timestamp, None, None, None)
        normalized["event_time"] = None
    else:
        timestamp_result = canonicalize_timestamp(
            raw_timestamp,
            assumed_timezone=assumed_timezone,
            naive_fold=naive_fold,
            epoch_unit=epoch_unit,
        )
        if timestamp_result.success:
            normalized["event_time"] = timestamp_result.canonical_timestamp
        else:
            normalized["event_time"] = None
            issues.extend(_issue_for_timestamp(timestamp_result))
        if timestamp_result.success:
            issues.extend(_issue_for_timestamp(timestamp_result))

    conversions: List[ConversionResult] = []
    raw_value = normalized.get("value")
    explicit_unit = normalized.get("unit")
    value_header = selected_headers.get("value")
    explicit_detection = detect_unit(explicit_unit)
    header_detection = detect_unit(field_name=value_header) if value_header else UnitDetection(
        False, None, None, None, None
    )

    # An explicit source unit wins only when it does not disagree with an
    # independently declared header unit.  Conflict means no conversion.
    unit_conflict = (
        explicit_detection.recognized
        and header_detection.recognized
        and explicit_detection.unit != header_detection.unit
    )
    if unit_conflict:
        issues.append(
            _issue(
                "unit_conflict",
                "error",
                "unit",
                "Explicit unit conflicts with the value-column header unit.",
            )
        )
    elif not _is_missing(explicit_unit) and not explicit_detection.recognized:
        issues.append(
            _issue("unknown_unit", "warning", "unit", "Unit is not in the safe conversion registry."))
    elif "ambiguous_header_unit" in header_detection.warning_codes:
        issues.append(
            _issue(
                "ambiguous_header_unit",
                "warning",
                "value",
                "Value-column header declares more than one recognizable unit.",
            )
        )

    # Do not use a header-derived unit when the source provided an explicit,
    # unrecognized unit.  It may be a typo or an unsupported dimension, and
    # replacing it would turn an evidence-preservation step into a guess.
    chosen_unit = explicit_detection if not _is_missing(explicit_unit) else header_detection
    if not _is_missing(raw_value) and not unit_conflict and chosen_unit.recognized:
        conversion = convert_value(raw_value, chosen_unit.unit)
        conversions.append(conversion)
        if conversion.success:
            normalized["value"] = conversion.value
            normalized["unit"] = conversion.to_unit
        else:
            normalized["value"] = None
            issues.append(
                _issue(
                    conversion.reason_code or "invalid_numeric_value",
                    "error",
                    "value",
                    "Value could not be converted using the declared unit.",
                )
            )
    elif not _is_missing(raw_value):
        numeric = _to_decimal(raw_value)
        if numeric is not None:
            normalized["value"] = _decimal_to_output(numeric)
        elif chosen_unit.recognized:
            # This branch is normally covered above but retains a direct guard
            # if a future caller supplies a nonstandard UnitDetection.
            normalized["value"] = None
            issues.append(
                _issue("invalid_numeric_value", "error", "value", "Unit-bearing value must be numeric."))

    mapping_aids = dict(mapping_aids)
    mapping_aids["resolved_mapping"] = {
        header: resolved_mapping[header] for header in sorted(resolved_mapping)
    }
    mapping_aids["selected_source_headers"] = dict(sorted(selected_headers.items()))
    quality = score_data_quality(normalized, issues, required_fields=required_fields)
    return NormalizedEvidenceRow(
        normalized_row=normalized,
        schema_mapping=mapping_aids,
        conversions=tuple(conversions),
        timestamp=timestamp_result,
        quality=quality,
        unmapped_fields=unmapped_fields,
    )


class OperationalEvidenceNormalizer:
    """Configurable, stateless facade for deterministic row normalization."""

    def __init__(
        self,
        *,
        assumed_timezone: Any = "UTC",
        naive_fold: Optional[int] = None,
        epoch_unit: Optional[str] = None,
        required_fields: Sequence[str] = DEFAULT_REQUIRED_FIELDS,
        field_mapping: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.assumed_timezone = assumed_timezone
        self.naive_fold = naive_fold
        self.epoch_unit = epoch_unit
        self.required_fields = tuple(required_fields)
        self.field_mapping = dict(field_mapping or {})

    def mapping_aids(self, headers: Iterable[Any]) -> Dict[str, Any]:
        """Expose conservative schema and wide-measurement hints for a source."""

        result = suggest_schema_mapping(headers)
        result["measurement_columns"] = suggest_measurement_columns(headers)
        return result

    def normalize_row(
        self,
        row: Mapping[str, Any],
        *,
        field_mapping: Optional[Mapping[str, str]] = None,
    ) -> NormalizedEvidenceRow:
        """Normalize a row with this facade's declared assumptions."""

        combined_mapping = dict(self.field_mapping)
        if field_mapping:
            combined_mapping.update(field_mapping)
        return normalize_operational_evidence_row(
            row,
            field_mapping=combined_mapping or None,
            assumed_timezone=self.assumed_timezone,
            naive_fold=self.naive_fold,
            epoch_unit=self.epoch_unit,
            required_fields=self.required_fields,
        )

    def normalize_rows(self, rows: Iterable[Mapping[str, Any]]) -> List[NormalizedEvidenceRow]:
        """Normalize rows independently; no clock, I/O, or mutable state is used."""

        return [self.normalize_row(row) for row in rows]


__all__ = [
    "CANONICAL_EVIDENCE_FIELDS",
    "DEFAULT_REQUIRED_FIELDS",
    "ConversionResult",
    "DataQualityReport",
    "NormalizationIssue",
    "NormalizedEvidenceRow",
    "OperationalEvidenceNormalizer",
    "TimestampNormalization",
    "UnitDetection",
    "canonicalize_timestamp",
    "convert_value",
    "detect_unit",
    "normalize_header",
    "normalize_operational_evidence_row",
    "score_data_quality",
    "suggest_measurement_columns",
    "suggest_schema_mapping",
]
