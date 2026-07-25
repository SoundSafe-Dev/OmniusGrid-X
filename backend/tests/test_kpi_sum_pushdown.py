"""Characterization + push-down guard for the two trip-SUM KPI endpoints.

get_cost_per_mile and get_fuel_efficiency loaded every trip row for the range
just to sum distance_miles (fuel-efficiency also built a per-vehicle distance
map that the response never uses). This pins their exact numbers and asserts the
sum is computed in SQL (SELECT sum(...)) rather than by loading rows.

Deferred (need the rows / grouped aggregation, characterize separately): idle-
time (per-vehicle group), on-time (per-carrier group), vehicle-health (per-row
score), dtc-count (by_system grouping uses a Python prefix function).
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api import kpi
from app.db.models import Base, GeoTabTrip


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


ORG = uuid4()
NOW = datetime.now(timezone.utc)


async def _factory_and_seed():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[GeoTabTrip.__table__])
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        s.add_all([
            # in range (this month)
            GeoTabTrip(id=uuid4(), organization_id=ORG, device_id="D1", vehicle_id="V1",
                       start_time=NOW - timedelta(days=1), distance_miles=100),
            GeoTabTrip(id=uuid4(), organization_id=ORG, device_id="D1", vehicle_id="V1",
                       start_time=NOW - timedelta(days=2), distance_miles=50.5),
            # NULL distance -> treated as 0 (coalesce)
            GeoTabTrip(id=uuid4(), organization_id=ORG, device_id="D2", vehicle_id="V2",
                       start_time=NOW - timedelta(days=3), distance_miles=None),
            # out of the month range -> excluded
            GeoTabTrip(id=uuid4(), organization_id=ORG, device_id="D2", vehicle_id="V2",
                       start_time=NOW - timedelta(days=90), distance_miles=999),
        ])
        await s.commit()
    return engine, Session


def _capture(engine):
    stmts: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _c(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            stmts.append(statement)

    return stmts


def _is_sum_query(stmts) -> bool:
    # An aggregate query SELECTs sum(...) rather than the row's columns.
    return any(re.search(r"select\s+.*\bsum\s*\(", s, re.IGNORECASE | re.DOTALL)
               and "geotab_trips" in s.lower() for s in stmts)


EXPECTED_MILES = 150.5  # 100 + 50.5 + 0(null); the 999 is out of range


def test_cost_per_mile_exact_and_summed_in_sql():
    async def scenario():
        engine, Session = await _factory_and_seed()
        stmts = _capture(engine)
        async with Session() as s:
            out = await kpi.get_cost_per_mile(range="month", org_id=ORG, db=s)
        await engine.dispose()
        return out, stmts

    out, stmts = run(scenario())
    assert out["total_miles"] == EXPECTED_MILES, out
    assert out["total_cost"] == round(EXPECTED_MILES * kpi._COST_PER_MILE_USD, 2)
    assert out["average_cost_per_mile"] == kpi._COST_PER_MILE_USD
    assert _is_sum_query(stmts), (
        "cost-per-mile still loads rows instead of SUM-ing in SQL:\n"
        + "\n".join(stmts)
    )


def test_fuel_efficiency_total_distance_exact_and_summed_in_sql():
    async def scenario():
        engine, Session = await _factory_and_seed()
        stmts = _capture(engine)
        async with Session() as s:
            out = await kpi.get_fuel_efficiency(range="month", org_id=ORG, db=s)
        await engine.dispose()
        return out, stmts

    out, stmts = run(scenario())
    assert out["total_distance"] == EXPECTED_MILES, out
    assert _is_sum_query(stmts), (
        "fuel-efficiency still loads rows instead of SUM-ing in SQL:\n"
        + "\n".join(stmts)
    )
