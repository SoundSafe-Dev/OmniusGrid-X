"""Config-driven local alerting wired into the collector message path.

Alert rules are declared per asset (a collector's ``config.alerts`` list) and
registered via :func:`configure` at startup; :func:`record` then evaluates each
reading's numeric payload against them, incrementing ``edge_alert_triggered_total``
when a rule fires. Activates the previously-dead LocalAlertingEngine.
"""

from typing import Any, Dict, List, Optional

import structlog

from .local_alerting import AlertRule, AlertSeverity, LocalAlertingEngine
from .anomaly_tracker import _iter_numeric
from .. import metrics

logger = structlog.get_logger()


def _severity(name: Any) -> AlertSeverity:
    """Coerce a config severity string to an AlertSeverity (defaults to WARNING)."""
    if isinstance(name, AlertSeverity):
        return name
    try:
        return AlertSeverity(str(name).lower())
    except ValueError:
        try:
            return AlertSeverity[str(name).upper()]
        except KeyError:
            return AlertSeverity.WARNING


class AlertingTracker:
    def __init__(self) -> None:
        self._engines: Dict[str, LocalAlertingEngine] = {}

    def configure(self, asset_id: str, rules: Optional[List[Dict[str, Any]]]) -> None:
        """Register alert rules for an asset (idempotent per asset)."""
        if not rules:
            return
        engine = LocalAlertingEngine(asset_id)
        engine.add_alert_handler(lambda alert, aid=asset_id: metrics.record_alert(aid, alert))
        for r in rules:
            try:
                engine.add_rule(AlertRule(
                    rule_id=r["rule_id"],
                    metric_name=r["metric_name"],
                    condition=r.get("condition", ">"),
                    threshold=float(r["threshold"]),
                    severity=_severity(r.get("severity", "warning")),
                    message_template=r.get("message_template", "{value} breached {threshold}"),
                    cooldown_seconds=int(r.get("cooldown_seconds", 300)),
                ))
            except (KeyError, ValueError, TypeError) as e:
                logger.error("invalid_alert_rule", asset_id=asset_id, rule=r, error=str(e))
        self._engines[asset_id] = engine

    def record(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        asset_id = message.get("asset_id")
        payload = message.get("payload") or {}
        engine = self._engines.get(asset_id) if asset_id else None
        if engine is None or not isinstance(payload, dict):
            return []
        fired: List[Dict[str, Any]] = []
        for metric, value in _iter_numeric(payload):
            fired.extend(engine.evaluate_telemetry(metric, value))
        return fired


_default = AlertingTracker()


def configure(asset_id: str, rules: Optional[List[Dict[str, Any]]]) -> None:
    _default.configure(asset_id, rules)


def record(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _default.record(message)


def reset() -> None:
    global _default
    _default = AlertingTracker()
