"""Characterization + push-down guard for get_on_time_performance.

It loaded every delivered shipment in the range and computed on-time/late and
per-carrier rates in Python. The refactor does one GROUP BY carrier_id with a
CASE for the on-time test and rebuilds the dict Python-side (same rounding).

The on-time rule is `scheduled_delivery IS NULL OR actual_delivery <=
scheduled_delivery`. The query already filters actual_delivery IS NOT NULL, so
the Python `s.actual_delivery and ...` guard is always truthy and the SQL CASE
matches it exactly. Both an on-time-via-NULL-schedule row and a NULL-carrier row
are seeded so a refactor that mishandles either fails.
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
from app.db.models import Base, Carrier, Shipment


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


ORG = uuid4()
C1, C2 = uuid4(), uuid4()
NOW = datetime.now(timezone.utc)


async def _factory_and_seed():
    engine = sqlite_engine()
    # FK-enforcing engine, and a `create_all` that closes over the tables these
    # reference (FS-410). `create_all(tables=[X])` builds X's foreign keys pointing at
    # tables it does not create, so with enforcement on every insert into X is refused.
    await create_all(engine, Base.metadata, [Shipment.__table__])
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    n = 0

    def ship(carrier, sched, actual, days=1, status="delivered"):
        nonlocal n
        n += 1
        return Shipment(
            id=uuid4(), organization_id=ORG, carrier_id=carrier,
            shipment_number=f"S{n}", status=status,
            scheduled_delivery=sched, actual_delivery=actual,
            updated_at=NOW - timedelta(days=days),
        )

    base = NOW - timedelta(days=1)
    async with Session() as s:
        # The organisation these rows belong to. With foreign keys enforced a bare
        # `organization_id = uuid4()` is refused, exactly as Postgres refuses it.
        s.add(minimal_organization(ORG))
        await s.flush()
        # And the two carriers the shipments below are attributed to — the whole point of
        # this test is that on-time rate is grouped by carrier IN SQL.
        for carrier_id, name in ((C1, "Carrier One"), (C2, "Carrier Two")):
            s.add(Carrier(id=str(carrier_id), organization_id=str(ORG), carrier_name=name))
        await s.flush()
        s.add_all([
            ship(C1, base, base - timedelta(hours=1)),   # C1 on-time
            ship(C1, base, base + timedelta(hours=1)),   # C1 late
            ship(C2, None, base),                        # C2 on-time via NULL schedule
            ship(None, base, base - timedelta(hours=2)), # NULL carrier, on-time
            ship(C1, base, base, days=90),               # out of range -> excluded
            ship(C1, base, None),                        # not-yet-delivered -> excluded (actual NULL)
            ship(C1, base, base, status="in_transit"),   # not delivered -> excluded
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


def test_on_time_exact_and_grouped_in_sql():
    async def scenario():
        engine, Session = await _factory_and_seed()
        stmts = _capture(engine)
        async with Session() as s:
            out = await kpi.get_on_time_performance(range="month", org_id=ORG, db=s)
        await engine.dispose()
        return out, stmts

    out, stmts = run(scenario())

    # In range + delivered + actual set: C1 on-time, C1 late, C2 on-time,
    # NULL-carrier on-time -> on_time=3, late=1, total=4 -> 75.0.
    assert out["on_time_count"] == 3, out
    assert out["late_count"] == 1, out
    assert out["overall_percentage"] == 75.0, out
    # by_carrier excludes the NULL carrier.
    assert set(out["by_carrier"]) == {str(C1), str(C2)}, out["by_carrier"]
    assert out["by_carrier"][str(C1)] == 50.0     # 1 of 2 on time
    assert out["by_carrier"][str(C2)] == 100.0    # 1 of 1 (NULL schedule = on time)

    ship_sql = [s for s in stmts if "shipments" in s.lower()]
    assert ship_sql, "no shipments query issued"
    assert any(re.search(r"group\s+by", s, re.IGNORECASE) for s in ship_sql), (
        "on-time still loads rows instead of GROUP BY in SQL:\n" + "\n".join(ship_sql)
    )
