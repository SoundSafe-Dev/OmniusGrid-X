"""Tests for edge-fleet liveness + metrics (tasks 17, 18)."""

from datetime import datetime, timedelta, timezone

from app.services.edge_fleet import (
    OFFLINE_AFTER_SECONDS,
    STALE_AFTER_SECONDS,
    agent_liveness,
    edge_agent_buffer_pending,
    edge_agent_up,
    update_fleet_metrics,
)

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def test_liveness_online_stale_offline():
    assert agent_liveness(NOW - timedelta(seconds=10), NOW) == "online"
    assert agent_liveness(NOW - timedelta(seconds=STALE_AFTER_SECONDS + 10), NOW) == "stale"
    assert agent_liveness(NOW - timedelta(seconds=OFFLINE_AFTER_SECONDS + 10), NOW) == "offline"
    assert agent_liveness(None, NOW) == "offline"


def test_liveness_treats_naive_as_utc():
    naive = (NOW - timedelta(seconds=5)).replace(tzinfo=None)
    assert agent_liveness(naive, NOW) == "online"


def test_update_fleet_metrics_publishes_gauges():
    update_fleet_metrics(
        "agent-metrics-test",
        {"buffer_pending": 42, "dead_lettered": 3, "active_collectors": 2, "cert_expires_in_seconds": 900},
        live="online",
    )
    assert edge_agent_up.labels(agent_id="agent-metrics-test")._value.get() == 1
    assert edge_agent_buffer_pending.labels(agent_id="agent-metrics-test")._value.get() == 42
