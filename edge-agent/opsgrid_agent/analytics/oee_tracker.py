"""Local OEE tracking wired into the collector message path.

Consumes the ``packml_state`` that collectors emit (mature collectors natively,
new collectors via the adapter's optional PackML mapping), maintaining a
per-asset :class:`LocalOEECalculator` and publishing ``edge_oee_*`` gauges. This
activates the previously-dead local OEE calculator without touching collectors.

Relative imports keep it independent of the omniusgrid_agent -> opsgrid_agent rename.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import structlog

from .local_oee import LocalOEECalculator
from .. import metrics

logger = structlog.get_logger()


def _parse_ts(raw: Any) -> datetime:
    """Parse an edge timestamp to aware UTC.

    This used to produce LOCAL NAIVE time, because `LocalOEECalculator` measured elapsed
    time against a bare `datetime.now()`. Two things were wrong with that (FS-461):

    * the docstring's premise had gone stale — it said collectors "mostly emit local-naive"
      timestamps, and by then seven of eleven emitted aware UTC. The five that did not were
      writing a naive local stamp into a `timestamptz` column, wrong by the device's offset,
      and are fixed too; **every collector emits aware UTC now**;
    * local wall-clock time is not monotonic. On a DST fall-back it steps BACKWARDS an
      hour, so the "currently in Execute" term `now - last_change` goes negative and
      silently subtracts from operating time — which feeds availability and performance.
      Once a year, on a number nobody would think to question.

    The naive branch below is kept deliberately, not left over: this parses messages off a
    buffer that can hold days of backlog written by an older agent build, and a stamp that
    predates the fix must still land somewhere sensible. `astimezone(timezone.utc)` reads a
    naive datetime as local, which is what those older stamps meant.
    """
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(raw) if raw else datetime.now(timezone.utc)
        except (ValueError, TypeError):
            dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc)


class OEETracker:
    """Per-asset local OEE from the collector message stream."""

    def __init__(self) -> None:
        self._calcs: Dict[str, LocalOEECalculator] = {}
        self._last: Dict[str, Tuple[str, datetime]] = {}

    def record(self, message: Dict[str, Any]) -> Optional[Dict[str, float]]:
        payload = message.get("payload") or {}
        state = message.get("packml_state") or payload.get("packml_state")
        asset_id = message.get("asset_id")
        if not state or not asset_id:
            return None

        ts = _parse_ts(message.get("timestamp_edge"))
        calc = self._calcs.get(asset_id)
        if calc is None:
            calc = self._calcs[asset_id] = LocalOEECalculator(asset_id)

        prev = self._last.get(asset_id)
        if prev is not None:
            prev_state, prev_ts = prev
            if prev_state != state:
                duration = max(0.0, (ts - prev_ts).total_seconds())
                calc.add_state_change(state, prev_state, ts, duration)
        self._last[asset_id] = (state, ts)

        # Feed production counts when telemetry carries them.
        total = payload.get("total_parts", payload.get("parts_total"))
        if total is not None:
            good = payload.get("good_parts", total)
            try:
                calc.add_production_count(int(total), int(good))
            except (TypeError, ValueError):
                pass

        result = calc.calculate_oee()
        metrics.set_oee(asset_id, result)
        return result


# Module-level default so the coordinator can call oee_tracker.record(message)
# without holding tracker state itself (mirrors the metrics module pattern).
_default = OEETracker()


def record(message: Dict[str, Any]) -> Optional[Dict[str, float]]:
    return _default.record(message)


def reset() -> None:
    """Reset the default tracker (used by tests)."""
    global _default
    _default = OEETracker()
