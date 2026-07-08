"""Deadband + rate-limit filtering (task 8).

Suppresses readings that carry no meaningful change, cutting uplink volume and
downstream storage without losing signal. A per-(asset, metric) state tracks the
last *forwarded* value and time; a new reading is forwarded when any holds:

* it moved more than the configured deadband (absolute or percent), OR
* at least ``min_interval_seconds`` have not yet elapsed is *false* — i.e. the
  min-interval gate has opened, AND there is any change, OR
* ``max_interval_seconds`` elapsed since the last forward (heartbeat), so a
  flat-lining sensor still proves liveness.

Deadband is evaluated on the canonical value so thresholds are unit-stable.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass
class _MetricState:
    last_value: float
    last_forward_ts: float


class DeadbandFilter:
    """Stateful deadband/rate-limit gate, one instance per collector."""

    def __init__(self) -> None:
        self._state: Dict[Tuple[str, str], _MetricState] = {}

    def should_forward(
        self,
        asset_id: str,
        metric: str,
        value: float,
        now: float,
        deadband: Optional[float] = None,
        deadband_percent: Optional[float] = None,
        min_interval_seconds: Optional[float] = None,
        max_interval_seconds: Optional[float] = None,
    ) -> bool:
        """Decide whether this reading passes the deadband/rate-limit gate."""
        key = (asset_id, metric)
        prev = self._state.get(key)

        # First reading for this metric always forwards and seeds the baseline.
        if prev is None:
            self._state[key] = _MetricState(value, now)
            return True

        elapsed = now - prev.last_forward_ts

        # Heartbeat: force a forward if the sensor has gone quiet too long.
        if max_interval_seconds is not None and elapsed >= max_interval_seconds:
            self._state[key] = _MetricState(value, now)
            return True

        # Min-interval: never forward more often than this regardless of change.
        if min_interval_seconds is not None and elapsed < min_interval_seconds:
            return False

        change = abs(value - prev.last_value)
        significant = False
        if deadband is not None and change >= deadband:
            significant = True
        if deadband_percent is not None:
            base = abs(prev.last_value)
            threshold = base * (deadband_percent / 100.0)
            if change >= threshold:
                significant = True
        # No deadband configured -> any reading past the min-interval forwards.
        if deadband is None and deadband_percent is None:
            significant = True

        if significant:
            self._state[key] = _MetricState(value, now)
            return True
        return False
