"""FS-105: Prometheus metrics for the newly-merged subsystems.

Pure-python assertions (no database) that the new metric objects exist in the
default registry and increment along the real code paths: RUL assessments,
digital-twin optimize runs, historian query metrics, and notification
dispatches.
"""

from uuid import uuid4

from prometheus_client import REGISTRY

from app.services.health_index import HealthResult
from app.services.notifications import NotificationService
from app.services.rul import RULService
from app.services.twin_optimizer import CandidateAction, SimulationPlan, TwinOptimizer


def _value(name: str, labels: dict | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


# --------------------------------------------------------------------------- #
# RUL
# --------------------------------------------------------------------------- #
class _FakeHealthCalculator:
    def __init__(self, result: HealthResult):
        self._result = result

    async def get_asset_health(self, asset_id: str, hours: int = 24) -> HealthResult:
        return self._result


class _FakeNotifier:
    def __init__(self):
        self.dispatched = []

    async def dispatch(self, event, organization_id=None):
        self.dispatched.append(event)
        return [{"delivered": True}]


async def test_rul_assessment_metrics_increment():
    health = HealthResult(asset_id="asset-1", health_score=2.0, confidence=1.0)
    service = RULService(
        health_calculator=_FakeHealthCalculator(health),
        notifier=_FakeNotifier(),
    )

    assessment = await service.assess_asset(
        "asset-1", uuid4(), dispatch_notification=True
    )
    assert assessment.risk_level in ("high", "critical")

    before_assess = _value(
        "opsgrid_rul_assessments_total", {"risk_level": assessment.risk_level}
    )
    before_alert = _value(
        "opsgrid_rul_low_rul_alerts_total", {"risk_level": assessment.risk_level}
    )
    before_latency = _value("opsgrid_rul_assessment_duration_seconds_count")

    await service.assess_asset("asset-1", uuid4(), dispatch_notification=True)

    assert (
        _value("opsgrid_rul_assessments_total", {"risk_level": assessment.risk_level})
        == before_assess + 1
    )
    assert (
        _value(
            "opsgrid_rul_low_rul_alerts_total",
            {"risk_level": assessment.risk_level},
        )
        == before_alert + 1
    )
    assert _value("opsgrid_rul_assessment_duration_seconds_count") == before_latency + 1


# --------------------------------------------------------------------------- #
# Digital-twin optimizer
# --------------------------------------------------------------------------- #
class _FakeSimulator:
    @staticmethod
    def monte_carlo_throughput(**kwargs):
        mean = 3600.0 / kwargs["cycle_time_seconds"]
        return {
            "throughput": {"mean": mean, "p10": mean * 0.9, "p90": mean * 1.1},
            "downtime_hours": {"mean": 4.0},
            "availability_mean": 0.9,
        }

    @staticmethod
    def fleet_oee_rollup(assets):
        return {"asset_count": 0}


def test_twin_optimizer_metrics_increment():
    optimizer = TwinOptimizer(
        simulator=_FakeSimulator(), recommendation_engine=None
    )
    candidate = CandidateAction(
        action_id="faster-cycle",
        name="Reduce cycle time",
        description="Halve the cycle time",
        parameter_overrides={"cycle_time_seconds": 30.0},
    )

    before_runs = _value("opsgrid_twin_optimize_runs_total")
    before_recs = _value("opsgrid_twin_recommendations_total")
    before_latency = _value("opsgrid_twin_optimize_run_duration_seconds_count")

    result = optimizer.evaluate("org-1", SimulationPlan(), [candidate], [])
    assert len(result.recommendations) == 1

    assert _value("opsgrid_twin_optimize_runs_total") == before_runs + 1
    assert _value("opsgrid_twin_recommendations_total") == before_recs + 1
    assert (
        _value("opsgrid_twin_optimize_run_duration_seconds_count")
        == before_latency + 1
    )


# --------------------------------------------------------------------------- #
# Historian
# --------------------------------------------------------------------------- #
def test_historian_metric_objects_exist_and_increment():
    from app.api.historian import (
        HISTORIAN_QUERIES_TOTAL,
        HISTORIAN_QUERY_DURATION,
        HISTORIAN_ROWS_RETURNED,
    )

    before_queries = _value(
        "opsgrid_historian_queries_total", {"granularity": "raw"}
    )
    before_latency = _value(
        "opsgrid_historian_query_duration_seconds_count", {"granularity": "raw"}
    )
    before_rows = _value("opsgrid_historian_rows_returned_count")

    HISTORIAN_QUERIES_TOTAL.labels(granularity="raw").inc()
    HISTORIAN_QUERY_DURATION.labels(granularity="raw").observe(0.01)
    HISTORIAN_ROWS_RETURNED.observe(42)

    assert (
        _value("opsgrid_historian_queries_total", {"granularity": "raw"})
        == before_queries + 1
    )
    assert (
        _value(
            "opsgrid_historian_query_duration_seconds_count",
            {"granularity": "raw"},
        )
        == before_latency + 1
    )
    assert _value("opsgrid_historian_rows_returned_count") == before_rows + 1


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
def test_notification_dispatch_metrics_by_channel_and_status():
    def ok_channel(target, event):
        return True, "delivered"

    def broken_channel(target, event):
        raise RuntimeError("boom")

    service = NotificationService(
        channels={"webhook": ok_channel, "slack": broken_channel}
    )
    event = {"severity": "critical", "title": "t", "message": "m"}
    rules = [
        {"id": "1", "channel": "webhook", "target": "http://x", "min_severity": "info"},
        {"id": "2", "channel": "slack", "target": "http://y", "min_severity": "info"},
    ]

    before_ok = _value(
        "opsgrid_notification_dispatches_total",
        {"channel": "webhook", "status": "success"},
    )
    before_fail = _value(
        "opsgrid_notification_dispatches_total",
        {"channel": "slack", "status": "failure"},
    )
    before_unknown = _value(
        "opsgrid_notification_dispatches_total",
        {"channel": "unknown", "status": "failure"},
    )
    before_latency = _value(
        "opsgrid_notification_delivery_duration_seconds_count",
        {"channel": "webhook"},
    )

    results = service.dispatch_rules(event, rules)
    assert [r["delivered"] for r in results] == [True, False]

    service.deliver("carrier-pigeon", "roof", event)

    assert (
        _value(
            "opsgrid_notification_dispatches_total",
            {"channel": "webhook", "status": "success"},
        )
        == before_ok + 1
    )
    assert (
        _value(
            "opsgrid_notification_dispatches_total",
            {"channel": "slack", "status": "failure"},
        )
        == before_fail + 1
    )
    assert (
        _value(
            "opsgrid_notification_dispatches_total",
            {"channel": "unknown", "status": "failure"},
        )
        == before_unknown + 1
    )
    assert (
        _value(
            "opsgrid_notification_delivery_duration_seconds_count",
            {"channel": "webhook"},
        )
        == before_latency + 1
    )
