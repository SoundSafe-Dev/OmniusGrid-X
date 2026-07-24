"""Characterization + N+1 guard for GeoTabService.get_device_trips.

The per-trip exception counts were fetched with a separate query inside the trip
loop (one SELECT on geotab_exceptions per trip = N+1). This test locks the exact
output (so the fix can't change a single count) and asserts the query count no
longer scales with the number of trips.

In-memory SQLite: get_device_trips takes a session and reads two tables; no RLS
or tenant GUC is involved, so SQLite is sufficient and fast.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, GeoTabTrip, GeoTabException
from app.services.geotab_service import GeoTabService


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[GeoTabTrip.__table__, GeoTabException.__table__],
        )
    return engine, sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


DEVICE = "GEO-DEVICE-1"
T0 = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)


async def _seed(session, org_id):
    # Three trips, newest last; the service returns them start_time DESC.
    trips = [
        GeoTabTrip(
            id=uuid4(), device_id=DEVICE, organization_id=org_id,
            start_time=T0 + timedelta(hours=h),
            end_time=T0 + timedelta(hours=h, minutes=30),
            duration_seconds=1800, idle_time_seconds=300, distance_miles=10,
            meta_data={"max_speed": 60},
        )
        for h in (0, 2, 4)
    ]
    session.add_all(trips)
    # Exceptions: place known types inside specific trip windows, plus one of an
    # unknown type (must be ignored) and one outside every window.
    excs = [
        # trip @ +0h  -> 2 harsh_braking, 1 speeding
        GeoTabException(id=uuid4(), device_id=DEVICE, organization_id=org_id,
                        exception_type="harsh_braking", timestamp=T0 + timedelta(minutes=5)),
        GeoTabException(id=uuid4(), device_id=DEVICE, organization_id=org_id,
                        exception_type="harsh_braking", timestamp=T0 + timedelta(minutes=10)),
        GeoTabException(id=uuid4(), device_id=DEVICE, organization_id=org_id,
                        exception_type="speeding", timestamp=T0 + timedelta(minutes=20)),
        # trip @ +2h  -> 1 harsh_acceleration
        GeoTabException(id=uuid4(), device_id=DEVICE, organization_id=org_id,
                        exception_type="harsh_acceleration",
                        timestamp=T0 + timedelta(hours=2, minutes=15)),
        # unknown type inside trip @ +4h  -> must be ignored
        GeoTabException(id=uuid4(), device_id=DEVICE, organization_id=org_id,
                        exception_type="seat_belt",
                        timestamp=T0 + timedelta(hours=4, minutes=5)),
        # outside every trip window -> counts for nothing
        GeoTabException(id=uuid4(), device_id=DEVICE, organization_id=org_id,
                        exception_type="speeding", timestamp=T0 + timedelta(hours=1, minutes=5)),
    ]
    session.add_all(excs)
    await session.commit()


# Expected per-trip event counts keyed by trip start hour (the fixed contract).
EXPECTED = {
    0: {"harsh_braking_events": 2, "harsh_acceleration_events": 0, "speeding_events": 1},
    2: {"harsh_braking_events": 0, "harsh_acceleration_events": 1, "speeding_events": 0},
    4: {"harsh_braking_events": 0, "harsh_acceleration_events": 0, "speeding_events": 0},
}


def _run_get_trips(count_queries: bool):
    async def scenario():
        engine, Session = await _session_factory()
        org_id = uuid4()
        async with Session() as session:
            await _seed(session, org_id)

        exec_count = {"n": 0}
        if count_queries:
            @event.listens_for(engine.sync_engine, "before_cursor_execute")
            def _c(conn, cursor, statement, params, context, executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    exec_count["n"] += 1

        async with Session() as session:
            trips = await GeoTabService().get_device_trips(
                device_id=DEVICE,
                from_time=T0 - timedelta(hours=1),
                to_time=T0 + timedelta(hours=6),
                organization_id=org_id,
                db=session,
            )
        await engine.dispose()
        return trips, exec_count["n"]

    return run(scenario())


def test_event_counts_are_exact():
    trips, _ = _run_get_trips(count_queries=False)
    by_hour = {
        datetime.fromisoformat(t["start_time"]).hour: t for t in trips
    }
    assert set(by_hour) == {8, 10, 12}  # T0 is 08:00; +2h, +4h
    for start_hour, expected in EXPECTED.items():
        row = by_hour[8 + start_hour]
        for key, val in expected.items():
            assert row[key] == val, f"trip +{start_hour}h {key}: {row[key]} != {val}"


def test_no_n_plus_one_on_exceptions():
    """Query count must not scale with the number of trips.

    Before the fix this issued 1 trips query + 1 exceptions query PER trip
    (3 trips -> 4 SELECTs). The fix fetches all exceptions once, so it is a
    constant 2 regardless of trip count.
    """
    _, n_queries = _run_get_trips(count_queries=True)
    assert n_queries <= 2, f"expected <=2 SELECTs (no N+1), got {n_queries}"
