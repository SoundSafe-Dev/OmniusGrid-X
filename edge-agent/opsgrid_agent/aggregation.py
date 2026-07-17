"""Batch / time-window aggregation before forward (task 23).

For high-frequency sensors that don't need per-sample fidelity in the cloud, the
agent can aggregate readings over a fixed time window into a single summary
(count/min/max/mean/last per metric), cutting uplink volume by orders of
magnitude while preserving the statistics dashboards and training actually use.
This is complementary to deadband (task 8): deadband drops unchanged points,
aggregation summarizes changing ones.

Aggregation is opt-in per collector and operates on numeric payload fields; the
window is time-based and flushed by :meth:`WindowAggregator.collect_due`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class _Accumulator:
    count: int = 0
    total: float = 0.0
    minimum: float = float("inf")
    maximum: float = float("-inf")
    last: float = 0.0

    def add(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.minimum = min(self.minimum, value)
        self.maximum = max(self.maximum, value)
        self.last = value

    def summary(self) -> Dict[str, float]:
        return {
            "count": self.count,
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.total / self.count if self.count else 0.0,
            "last": self.last,
        }


@dataclass
class _Window:
    started_at: float
    metrics: Dict[str, _Accumulator] = field(default_factory=dict)


class WindowAggregator:
    """Time-windowed per-(asset, metric) aggregator."""

    def __init__(self, window_seconds: float):
        self.window_seconds = window_seconds
        self._windows: Dict[str, _Window] = {}

    def add(self, asset_id: str, payload: Dict[str, Any], now: float) -> None:
        """Fold a reading's numeric fields into the asset's current window."""
        win = self._windows.get(asset_id)
        if win is None:
            win = self._windows[asset_id] = _Window(started_at=now)
        for key, value in payload.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            win.metrics.setdefault(key, _Accumulator()).add(float(value))

    def collect_due(self, now: float) -> List[Tuple[str, Dict[str, Any]]]:
        """Flush and return summaries for every window whose interval elapsed.

        Returns ``(asset_id, aggregated_payload)`` pairs; each metric maps to its
        summary dict. Emptied windows are removed so idle assets cost nothing.
        """
        due: List[Tuple[str, Dict[str, Any]]] = []
        for asset_id in list(self._windows.keys()):
            win = self._windows[asset_id]
            if now - win.started_at < self.window_seconds:
                continue
            if win.metrics:
                due.append(
                    (asset_id, {m: acc.summary() for m, acc in win.metrics.items()})
                )
            del self._windows[asset_id]
        return due
