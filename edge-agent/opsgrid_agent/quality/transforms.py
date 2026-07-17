"""Engineering-unit scaling / linear transforms (task 7).

Raw protocol values are frequently ADC counts, register words, or scaled
integers. A linear transform ``scaled = raw * gain + offset`` with optional
clamping maps them to engineering units. This runs before unit normalization so
the declared ``unit`` describes the scaled value, not the raw register.
"""

from typing import Optional


def apply_linear(
    raw: float,
    gain: float = 1.0,
    offset: float = 0.0,
    clamp_min: Optional[float] = None,
    clamp_max: Optional[float] = None,
) -> float:
    """Apply ``raw * gain + offset`` then optional clamping.

    Clamping guards against sensor spikes / wraparound producing absurd
    engineering values; it is applied after the affine map so the bounds are
    expressed in engineering units.
    """
    value = raw * gain + offset
    if clamp_min is not None and value < clamp_min:
        value = clamp_min
    if clamp_max is not None and value > clamp_max:
        value = clamp_max
    return value
