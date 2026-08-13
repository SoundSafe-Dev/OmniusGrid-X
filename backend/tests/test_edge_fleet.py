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


def test_a_heartbeat_stamps_the_staleness_watchdog():
    """FS-695. `edge_agent_up` is written only when a heartbeat ARRIVES, and its single
    call site hardcodes "online" — so an agent that stops heartbeating freezes the gauge
    at 1, and the old `edge_agent_up == 0` alert could never fire in production (its unit
    test passed by hand-writing a series nothing can produce). EdgeAgentOffline now ages
    this timestamp instead; every accepted heartbeat must move it, or the alert fires for
    a fleet that is perfectly healthy — and the other failure, a stamp that never moves,
    is the original defect back again."""
    import time as _time

    from app.services.edge_fleet import edge_agent_last_heartbeat

    update_fleet_metrics("agent-watchdog-test", {}, live="online")
    stamp = edge_agent_last_heartbeat.labels(agent_id="agent-watchdog-test")._value.get()
    assert abs(stamp - _time.time()) < 2.0, (
        f"the heartbeat stamp is {stamp}, not the current unix time — EdgeAgentOffline "
        f"computes time() minus this, so anything else breaks the age"
    )
