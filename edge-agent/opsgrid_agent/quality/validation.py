"""Per-reading schema validation (task 6).

Envelope validation is structural (is this a well-formed reading at all?);
per-metric range/finiteness checks live in the pipeline because they run *after*
scaling and unit normalization. Validators return a list of :class:`QualityFlag`
so the pipeline can accumulate flags across stages and decide one action.
"""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .flags import QualityFlag

# Envelope fields a reading must carry to be routable at all.
_REQUIRED_FIELDS = ("asset_id", "timestamp_edge")


def parse_edge_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 edge timestamp to an aware UTC datetime, or ``None``."""
    if not isinstance(value, str) or not value:
        return None
    try:
        # Accept trailing 'Z'; datetime.fromisoformat handles offsets on 3.11+.
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_envelope(
    reading: Dict[str, Any], now: datetime, staleness_seconds: Optional[float]
) -> List[QualityFlag]:
    """Check required fields, timestamp validity, and staleness.

    ``now`` is injected (not read from the clock) so validation is deterministic
    and testable, and so the pipeline shares one clock reading across stages.
    """
    flags: List[QualityFlag] = []

    for field in _REQUIRED_FIELDS:
        if not reading.get(field):
            flags.append(QualityFlag.MISSING_FIELD)
            break

    if not isinstance(reading.get("payload"), dict):
        flags.append(QualityFlag.MISSING_FIELD)

    dt = parse_edge_timestamp(reading.get("timestamp_edge"))
    if dt is None:
        # Only report BAD_TIMESTAMP if the field was present but unparseable;
        # a missing field is already covered above.
        if reading.get("timestamp_edge"):
            flags.append(QualityFlag.BAD_TIMESTAMP)
    else:
        # A timestamp far in the future is implausible clock skew, not staleness.
        if dt > now and (dt - now).total_seconds() > 60:
            flags.append(QualityFlag.BAD_TIMESTAMP)
        elif staleness_seconds is not None:
            age = (now - dt).total_seconds()
            if age > staleness_seconds:
                flags.append(QualityFlag.STALE)

    return flags


def check_numeric(
    value: Any, minimum: Optional[float], maximum: Optional[float]
) -> Tuple[Optional[float], List[QualityFlag]]:
    """Coerce to float and range-check. Returns (value_or_None, flags).

    Non-numeric values are left for the caller to pass through untouched (many
    payload fields are strings/enums); only numeric metrics are range-checked.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, []
    fval = float(value)
    if not math.isfinite(fval):
        return None, [QualityFlag.NON_FINITE]
    flags: List[QualityFlag] = []
    if minimum is not None and fval < minimum:
        flags.append(QualityFlag.OUT_OF_RANGE)
    if maximum is not None and fval > maximum:
        flags.append(QualityFlag.OUT_OF_RANGE)
    return fval, flags
