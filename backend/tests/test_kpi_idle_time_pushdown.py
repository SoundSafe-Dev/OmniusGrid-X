"""Characterization + push-down guard for get_idle_time.

It loaded every trip in the range and summed idle/run seconds per vehicle in
Python. The refactor does one GROUP BY vehicle_id in SQL and rebuilds the same
dict — Python-side rounding is unchanged, so the numbers are identical.

Key subtlety pinned here: the totals (total_hours / percentage_of_runtime)
include trips with a NULL vehicle_id, but the per-vehicle breakdown does not. A
NULL-vehicle trip is seeded so a refactor that folds it into by_vehicle, or drops
it from the totals, fails.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from tests._sqlite import create_all, minimal_organization, sqlite_engine
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
    engine = sqlite_engine()
    # FK-enforcing engine, and a `create_all` that closes over the tables these
    # reference (FS-410). `create_all(tables=[X])` builds X's foreign keys pointing at
    # tables it does not create, so with enforcement on every insert into X is refused.
    await create_all(engine, Base.metadata, [GeoTabTrip.__table__])
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def trip(vid, idle, dur, days):
        return GeoTabTrip(id=uuid4(), organization_id=ORG, device_id="D",
                          vehicle_id=vid, idle_time_seconds=idle,
                          duration_seconds=dur, start_time=NOW - timedelta(days=days))

    async with Session() as s:
        # The organisation these rows belong to. With foreign keys enforced a bare
        # `organization_id = uuid4()` is refused, exactly as Postgres refuses it.
        s.add(minimal_organization(ORG))
        await s.flush()
        s.add_all([
            trip("V1", 600, 3600, 1),     # V1: 600s idle / 3600s run
            trip("V1", 300, 1800, 2),     # V1 again -> 900 / 5400
            trip("V2", 1200, 2400, 3),    # V2: 1200 / 2400
            trip(None, 100, 500, 4),      # NULL vehicle: counts in totals only
            trip("V2", 0, 0, 90),         # out of range -> excluded
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


def test_idle_time_exact_and_grouped_in_sql():
    async def scenario():
        engine, Session = await _factory_and_seed()
        stmts = _capture(engine)
        async with Session() as s:
            out = await kpi.get_idle_time(range="month", org_id=ORG, db=s)
        await engine.dispose()
        return out, stmts

    out, stmts = run(scenario())

    # Totals include the NULL-vehicle trip: idle = 900+1200+100 = 2200s,
    # run = 5400+2400+500 = 8300s.
    assert out["total_hours"] == round(2200 / 3600, 2), out
    assert out["percentage_of_runtime"] == round(2200 / 8300 * 100, 1), out

    # by_vehicle excludes the NULL trip.
    assert set(out["by_vehicle"]) == {"V1", "V2"}, out["by_vehicle"]
    assert out["by_vehicle"]["V1"] == {
        "hours": round(900 / 3600, 2),
        "percentage": round(900 / 5400 * 100, 1),
        "cost": round((900 / 3600) * kpi._COST_PER_MILE_USD, 2),
    }
    assert out["by_vehicle"]["V2"]["percentage"] == round(1200 / 2400 * 100, 1)

    # Push-down: the trips read is a GROUP BY aggregate, not a full row load.
    trip_sql = [s for s in stmts if "geotab_trips" in s.lower()]
    assert trip_sql, "no trips query issued"
    assert any(re.search(r"group\s+by", s, re.IGNORECASE) for s in trip_sql), (
        "idle-time still loads rows instead of GROUP BY in SQL:\n"
        + "\n".join(trip_sql)
    )
