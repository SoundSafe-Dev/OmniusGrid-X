"""Quality flags and pipeline actions (task 10 vocabulary).

Kept in a tiny leaf module so every stage can import the enums without pulling in
the pipeline or config, avoiding import cycles.
"""

from enum import Enum


class QualityFlag(str, Enum):
    """Per-reading quality verdicts, attached under ``reading['quality']['flags']``.

    ``GOOD`` is never stored explicitly — a reading with no other flag is good.
    The remaining flags are additive: one reading can be both ``STALE`` and
    ``OUT_OF_RANGE``.
    """

    OUT_OF_RANGE = "out_of_range"      # numeric value outside configured min/max
    NON_FINITE = "non_finite"          # NaN / +-inf
    MISSING_FIELD = "missing_field"    # required envelope field absent/empty
    BAD_TIMESTAMP = "bad_timestamp"    # timestamp unparseable or implausible
    STALE = "stale"                    # reading older than the staleness horizon
    RATE_LIMITED = "rate_limited"      # suppressed by deadband/min-interval
    UNKNOWN_UNIT = "unknown_unit"      # unit not in the normalization registry


class QualityAction(str, Enum):
    """What the pipeline decided to do with a reading."""

    FORWARD = "forward"        # clean (or clean-enough) — hand to the buffer
    QUARANTINE = "quarantine"  # invalid — divert to the quarantine sink
    DROP = "drop"              # suppressed by deadband/rate-limit — discard silently
