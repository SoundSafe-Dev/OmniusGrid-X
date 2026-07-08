"""Unit-normalization registry (task 9).

Converts a value expressed in some source unit to its dimension's canonical unit
via a linear map ``canonical = value * factor + offset``. Linear covers every
industrial unit we care about (temperature, pressure, flow, ratios); non-linear
scales (dB, pH) are intentionally out of scope and treated as unknown units.

Canonical units per dimension:

    temperature -> degC
    pressure    -> kPa
    flow        -> l_min   (litres per minute)
    ratio       -> percent

Register new units with :func:`register_unit`; look up conversions with
:func:`to_canonical`.
"""

from typing import Dict, Optional, Tuple

import structlog

logger = structlog.get_logger()

# unit -> (dimension, factor, offset) such that canonical = raw * factor + offset
_REGISTRY: Dict[str, Tuple[str, float, float]] = {}

# canonical unit label per dimension
_CANONICAL: Dict[str, str] = {
    "temperature": "degC",
    "pressure": "kPa",
    "flow": "l_min",
    "ratio": "percent",
}


def register_unit(unit: str, dimension: str, factor: float, offset: float = 0.0) -> None:
    """Register a linear conversion from ``unit`` to its dimension canonical."""
    _REGISTRY[unit.lower()] = (dimension, factor, offset)


def _seed_defaults() -> None:
    # temperature -> degC
    register_unit("degc", "temperature", 1.0, 0.0)
    register_unit("c", "temperature", 1.0, 0.0)
    register_unit("degf", "temperature", 5.0 / 9.0, -160.0 / 9.0)  # (f-32)*5/9
    register_unit("f", "temperature", 5.0 / 9.0, -160.0 / 9.0)
    register_unit("k", "temperature", 1.0, -273.15)
    register_unit("kelvin", "temperature", 1.0, -273.15)
    # pressure -> kPa
    register_unit("kpa", "pressure", 1.0, 0.0)
    register_unit("pa", "pressure", 0.001, 0.0)
    register_unit("bar", "pressure", 100.0, 0.0)
    register_unit("psi", "pressure", 6.894757, 0.0)
    register_unit("atm", "pressure", 101.325, 0.0)
    register_unit("mbar", "pressure", 0.1, 0.0)
    # flow -> l/min
    register_unit("l_min", "flow", 1.0, 0.0)
    register_unit("lpm", "flow", 1.0, 0.0)
    register_unit("m3_h", "flow", 1000.0 / 60.0, 0.0)     # m^3/h -> l/min
    register_unit("gpm", "flow", 3.785412, 0.0)            # US gal/min -> l/min
    # ratio -> percent
    register_unit("percent", "ratio", 1.0, 0.0)
    register_unit("%", "ratio", 1.0, 0.0)
    register_unit("fraction", "ratio", 100.0, 0.0)         # 0..1 -> 0..100


_seed_defaults()


def to_canonical(value: float, unit: str) -> Optional[Tuple[float, str]]:
    """Convert ``value`` in ``unit`` to (canonical_value, canonical_unit).

    Returns ``None`` if the unit is not registered — the caller flags the reading
    ``UNKNOWN_UNIT`` and leaves the value unchanged rather than guessing.
    """
    entry = _REGISTRY.get(unit.lower())
    if entry is None:
        return None
    dimension, factor, offset = entry
    return value * factor + offset, _CANONICAL[dimension]
