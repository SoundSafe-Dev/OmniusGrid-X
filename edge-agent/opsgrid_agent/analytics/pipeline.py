"""Local analytics pipeline: single entrypoint run from the collector seam.

Runs the OEE, anomaly, and alerting trackers for each collector message so the
coordinator has one call site and future analytics stay additive.
"""

from typing import Any, Dict

from . import oee_tracker, anomaly_tracker, alerting_tracker


def record(message: Dict[str, Any]) -> None:
    oee_tracker.record(message)
    anomaly_tracker.record(message)
    alerting_tracker.record(message)


def reset() -> None:
    oee_tracker.reset()
    anomaly_tracker.reset()
    alerting_tracker.reset()
