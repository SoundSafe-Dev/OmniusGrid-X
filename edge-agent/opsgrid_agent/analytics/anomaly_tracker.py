"""Edge anomaly detection wired into the collector message path.

Feeds each numeric payload field of every reading into a per-asset
:class:`AnomalyDetector` (z-score) and publishes ``edge_anomaly_*`` metrics.
Activates the previously-dead anomaly detector without touching collectors.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Tuple

import structlog

from .anomaly_detection import AnomalyDetector
from .. import metrics

logger = structlog.get_logger()


def _iter_numeric(payload: Dict[str, Any]) -> Iterator[Tuple[str, float]]:
    """Yield (metric, value) numeric pairs, handling modbus's nested telemetry."""
    source = payload.get("telemetry") if isinstance(payload.get("telemetry"), dict) else payload
    for key, value in source.items():
        if key.startswith("packml_") or key in ("state", "status"):
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            yield key, float(value)


class AnomalyTracker:
    def __init__(self) -> None:
        self._detectors: Dict[str, AnomalyDetector] = {}

    def record(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        payload = message.get("payload") or {}
        asset_id = message.get("asset_id")
        if not asset_id or not isinstance(payload, dict):
            return []

        detector = self._detectors.get(asset_id)
        if detector is None:
            detector = self._detectors[asset_id] = AnomalyDetector(asset_id)

        found: List[Dict[str, Any]] = []
        for metric, value in _iter_numeric(payload):
            anomaly = detector.add_telemetry(metric, value, datetime.now(timezone.utc))
            if anomaly:
                metrics.record_anomaly(asset_id, anomaly)
                found.append(anomaly)
        return found


_default = AnomalyTracker()


def record(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _default.record(message)


def reset() -> None:
    global _default
    _default = AnomalyTracker()
