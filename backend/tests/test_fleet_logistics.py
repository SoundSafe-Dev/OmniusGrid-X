"""Tests for the fleet-logistics pure aggregates (tasks D20-D21)."""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.api.fleet_logistics import summarize_maintenance
from app.api.transportation import compute_delivery_efficiency

NOW = datetime(2026, 7, 9, 12, 0, 0)


def shipment(status="delivered", pickup=None, scheduled=None, actual=None):
    return SimpleNamespace(
        status=status, actual_pickup=pickup,
        scheduled_delivery=scheduled, actual_delivery=actual,
    )


def test_delivery_efficiency_on_time_rate_and_transit():
    shipments = [
        # on time: delivered 1h early, 10h transit
        shipment(pickup=NOW - timedelta(hours=10), scheduled=NOW + timedelta(hours=1), actual=NOW),
        # late: delivered 2h after schedule, 14h transit
        shipment(pickup=NOW - timedelta(hours=14), scheduled=NOW - timedelta(hours=2), actual=NOW),
        # not delivered -> excluded
        shipment(status="in_transit"),
    ]
    eff = compute_delivery_efficiency(shipments)
    assert eff["onTimeRate"] == 0.5
    assert eff["avgTransitHours"] == 12.0
    assert eff["totalDelivered"] == 2


def test_delivery_efficiency_empty_is_safe():
    eff = compute_delivery_efficiency([])
    assert eff["onTimeRate"] == 1.0
    assert eff["avgTransitHours"] == 0.0


def sched(status="scheduled", due=None):
    return SimpleNamespace(status=status, due_date=due)


def order(status="open", cost=None, completed=None, category=None):
    return SimpleNamespace(status=status, cost=cost, completed_at=completed, category=category)


def test_summarize_maintenance_counts_and_costs():
    schedules = [
        sched(due=NOW + timedelta(days=3)),                 # scheduled, not overdue
        sched(due=NOW - timedelta(days=1)),                 # overdue
        sched(status="completed", due=NOW - timedelta(days=9)),
    ]
    orders = [
        order(status="in_progress"),
        order(status="completed", cost=850.0, completed=NOW - timedelta(days=30), category="brakes"),
        order(status="completed", cost=150.0, completed=NOW - timedelta(days=10), category="brakes"),
        order(status="completed", cost=99.0, completed=NOW.replace(year=2025), category="tires"),  # prior year
    ]
    s = summarize_maintenance(schedules, orders, NOW)
    assert s["scheduledCount"] == 2
    assert s["overdueCount"] == 1
    assert s["activeRepairs"] == 1
    assert s["ytdCosts"] == 1000.0
    assert s["costsByCategory"] == {"brakes": 1000.0}
