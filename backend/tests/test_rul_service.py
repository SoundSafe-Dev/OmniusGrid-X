"""Focused tests for RUL calculation and recommendation delivery."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.health_index import HealthIndexCalculator
from app.services.notifications import NotificationService
from app.services.rul import RULService


def test_degraded_health_increases_failure_probability_and_reduces_rul():
    calculator = HealthIndexCalculator()
    now = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)
    healthy = RULService.calculate(
        calculator.compute("healthy", [90.0] * 6, now=now),
        now=now,
    )
    degraded = RULService.calculate(
        calculator.compute(
            "degraded",
            [40.0, 30.0, 20.0, 10.0, 5.0, 2.0],
            alarm_rate_per_hour=6.0,
            availability=40.0,
            now=now,
        ),
        now=now,
    )

    assert 0.0 <= healthy.failure_probability <= 1.0
    assert 0.0 <= degraded.failure_probability <= 1.0
    assert degraded.failure_probability > healthy.failure_probability
    assert degraded.remaining_useful_life_hours < healthy.remaining_useful_life_hours
    assert healthy.risk_level == "low"
    assert degraded.risk_level == "critical"
    assert degraded.model_source == "health_index_weibull_v1"


def test_maintenance_window_is_ordered_and_precedes_estimated_failure():
    calculator = HealthIndexCalculator()
    now = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)
    assessment = RULService.calculate(
        calculator.compute(
            "critical",
            [15.0, 10.0, 5.0],
            alarm_rate_per_hour=10.0,
            now=now,
        ),
        now=now,
    )
    window = assessment.recommended_maintenance_window

    assert window.urgency == "critical"
    assert window.start == now
    assert window.start < window.end
    assert window.end <= now + timedelta(hours=24)
    assert window.end < now + timedelta(
        hours=assessment.remaining_useful_life_hours
    )


@pytest.mark.asyncio
async def test_assessment_dispatches_through_real_notification_service(monkeypatch):
    sent = []
    recorded = []

    def deliver(target, event):
        sent.append((target, event))
        return True, "recorded"

    notifier = NotificationService(channels={"email": deliver})

    async def load_rules(organization_id):
        return [
            {
                "id": "subscription-1",
                "channel": "email",
                "target": "maintenance@example.test",
                "min_severity": "warning",
                "domain": "maintenance",
                "asset_id": "asset-1",
                "enabled": True,
            }
        ]

    async def record_deliveries(event, organization_id, results):
        recorded.append((event, organization_id, results))

    monkeypatch.setattr(notifier, "_load_rules", load_rules)
    monkeypatch.setattr(notifier, "_record_deliveries", record_deliveries)

    health_calculator = HealthIndexCalculator()

    async def get_asset_health(asset_id, hours=24):
        assert hours == 48
        return health_calculator.compute(
            asset_id,
            [20.0, 10.0, 5.0],
            alarm_rate_per_hour=8.0,
        )

    monkeypatch.setattr(
        health_calculator, "get_asset_health", get_asset_health
    )
    service = RULService(
        health_calculator=health_calculator,
        notifier=notifier,
    )
    organization_id = uuid4()

    assessment = await service.assess_asset(
        "asset-1",
        organization_id,
        health_window_hours=48,
        dispatch_notification=True,
    )

    assert assessment.notification_dispatched is True
    assert assessment.notification_delivery_count == 1
    assert len(sent) == 1
    assert len(recorded) == 1
    event = sent[0][1]
    assert event["event_type"] == "rul_recommendation"
    assert event["domain"] == "maintenance"
    assert event["organization_id"] == str(organization_id)
    assert event["maintenance_window"]["start"].endswith("+00:00")
