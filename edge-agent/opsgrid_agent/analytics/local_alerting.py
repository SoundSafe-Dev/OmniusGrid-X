"""Local Alerting Engine for Edge Agent"""

from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
import structlog

logger = structlog.get_logger()


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertRule:
    """Rule for generating alerts."""
    
    def __init__(
        self,
        rule_id: str,
        metric_name: str,
        condition: str,  # '>', '<', '>=', '<=', '==', '!='
        threshold: float,
        severity: AlertSeverity,
        message_template: str,
        cooldown_seconds: int = 300
    ):
        self.rule_id = rule_id
        self.metric_name = metric_name
        self.condition = condition
        self.threshold = threshold
        self.severity = severity
        self.message_template = message_template
        self.cooldown_seconds = cooldown_seconds
        self.last_triggered: Optional[datetime] = None
    
    def evaluate(self, value: float) -> bool:
        """Evaluate if the rule condition is met."""
        if self.condition == ">":
            return value > self.threshold
        elif self.condition == "<":
            return value < self.threshold
        elif self.condition == ">=":
            return value >= self.threshold
        elif self.condition == "<=":
            return value <= self.threshold
        elif self.condition == "==":
            return value == self.threshold
        elif self.condition == "!=":
            return value != self.threshold
        return False
    
    def can_trigger(self) -> bool:
        """Check if rule can trigger (respecting cooldown)."""
        if self.last_triggered is None:
            return True
        
        cooldown_expired = datetime.now() - self.last_triggered > timedelta(seconds=self.cooldown_seconds)
        return cooldown_expired
    
    def trigger(self, value: float) -> Dict[str, Any]:
        """Trigger the alert and update last triggered time."""
        self.last_triggered = datetime.now()
        
        return {
            "rule_id": self.rule_id,
            "metric_name": self.metric_name,
            "value": value,
            "threshold": self.threshold,
            "condition": self.condition,
            "severity": self.severity.value,
            "message": self.message_template.format(value=value, threshold=self.threshold),
            "timestamp": datetime.now().isoformat()
        }


class LocalAlertingEngine:
    """
    Local alerting engine for edge agent.
    
    Generates alerts based on rule-based conditions.
    """
    
    def __init__(self, asset_id: str):
        self.asset_id = asset_id
        self.rules: Dict[str, AlertRule] = {}
        self.alerts: List[Dict[str, Any]] = []
        self.alert_handlers: List[Callable[[Dict[str, Any]], None]] = []
    
    def add_rule(self, rule: AlertRule) -> None:
        """
        Add an alert rule.
        
        Args:
            rule: AlertRule to add
        """
        self.rules[rule.rule_id] = rule
        
        logger.info(
            "alert_rule_added",
            asset_id=self.asset_id,
            rule_id=rule.rule_id,
            metric_name=rule.metric_name
        )
    
    def remove_rule(self, rule_id: str) -> None:
        """
        Remove an alert rule.
        
        Args:
            rule_id: ID of rule to remove
        """
        if rule_id in self.rules:
            del self.rules[rule_id]
            
            logger.info(
                "alert_rule_removed",
                asset_id=self.asset_id,
                rule_id=rule_id
            )
    
    def add_alert_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """
        Add a handler to be called when an alert is generated.
        
        Args:
            handler: Function to call with alert data
        """
        self.alert_handlers.append(handler)
    
    def evaluate_telemetry(self, metric_name: str, value: float) -> List[Dict[str, Any]]:
        """
        Evaluate telemetry against all rules for the metric.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            
        Returns:
            List of generated alerts
        """
        generated_alerts = []
        
        for rule_id, rule in self.rules.items():
            if rule.metric_name != metric_name:
                continue
            
            if rule.evaluate(value) and rule.can_trigger():
                alert = rule.trigger(value)
                self.alerts.append(alert)
                generated_alerts.append(alert)
                
                # Keep only last 1000 alerts
                if len(self.alerts) > 1000:
                    self.alerts = self.alerts[-1000:]
                
                # Call alert handlers
                for handler in self.alert_handlers:
                    try:
                        handler(alert)
                    except Exception as e:
                        logger.error(
                            "alert_handler_failed",
                            rule_id=rule_id,
                            error=str(e)
                        )
                
                logger.warning(
                    "alert_triggered",
                    asset_id=self.asset_id,
                    rule_id=rule_id,
                    severity=alert["severity"]
                )
        
        return generated_alerts
    
    def get_recent_alerts(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get alerts from the last N hours.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            List of recent alerts
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        
        return [
            alert for alert in self.alerts
            if datetime.fromisoformat(alert["timestamp"]) > cutoff
        ]
    
    def get_alert_count(self, hours: int = 24) -> Dict[str, int]:
        """
        Get count of alerts by severity in the last N hours.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            Dictionary mapping severity to count
        """
        recent_alerts = self.get_recent_alerts(hours)
        
        counts = {"info": 0, "warning": 0, "error": 0, "critical": 0}
        for alert in recent_alerts:
            severity = alert["severity"]
            if severity in counts:
                counts[severity] += 1
        
        return counts
    
    def reset(self) -> None:
        """Reset all alerts and rules."""
        self.alerts.clear()
        self.rules.clear()
        self.alert_handlers.clear()
        
        logger.info("alerting_engine_reset", asset_id=self.asset_id)
