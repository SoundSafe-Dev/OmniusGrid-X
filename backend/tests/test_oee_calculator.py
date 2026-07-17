"""Unit tests for the backend OEE calculator (services.oee_calculator).

Drives calculate_oee from an in-memory state history with the DB-bound part-count
and ideal-cycle-time helpers monkeypatched, so no database is required. A sync
run() helper avoids a pytest-asyncio dependency.
"""

import asyncio
from datetime import datetime, timedelta

from app.services.oee_calculator import (
    OEECalculator,
    OEEMetrics,
    OEEStateCategory,
    StateTransition,
)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_state_category_mapping():
    calc = OEECalculator()
    assert calc._get_state_category("Execute") == OEEStateCategory.PRODUCTION
    assert calc._get_state_category("Idle") == OEEStateCategory.PLANNED_STOP
    assert calc._get_state_category("Stopped") == OEEStateCategory.PLANNED_STOP
    assert calc._get_state_category("Aborted") == OEEStateCategory.UNPLANNED_STOP
    assert calc._get_state_category("Held") == OEEStateCategory.UNPLANNED_STOP
    # Unknown states default to a planned stop (conservative).
    assert calc._get_state_category("Mystery") == OEEStateCategory.PLANNED_STOP


def test_calculate_oee_from_state_history():
    calc = OEECalculator()
    now = datetime.utcnow()
    calc._state_history["a1"] = [
        StateTransition(
            timestamp=now - timedelta(minutes=40),
            from_state="Execute", to_state="Stopped", duration_seconds=1800,
        ),
        StateTransition(
            timestamp=now - timedelta(minutes=10),
            from_state="Stopped", to_state="Execute", duration_seconds=600,
        ),
    ]

    async def fake_parts(asset_id, start, end):
        return {"total": 40, "good": 38, "rejected": 2}

    async def fake_ideal(asset_id):
        return 60.0

    calc._get_part_counts = fake_parts
    calc._get_ideal_cycle_time = fake_ideal

    m = run(calc.calculate_oee("a1", time_window_hours=1.0))

    assert isinstance(m, OEEMetrics)
    assert m.quality == 95.0                      # 38 / 40
    assert m.total_parts == 40 and m.good_parts == 38
    assert 0.0 <= m.availability <= 100.0
    # OEE == Availability x Performance x Quality (as percentages), within rounding.
    expected = round(m.availability / 100 * m.performance / 100 * m.quality / 100 * 100, 2)
    assert abs(m.oee - expected) < 0.5


def test_unknown_asset_returns_empty_metrics():
    calc = OEECalculator()
    m = run(calc.calculate_oee("does-not-exist"))
    assert m.oee == 0.0
    assert m.total_parts == 0
