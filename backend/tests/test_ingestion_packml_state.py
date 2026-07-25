"""Regression tests for the ingestion worker's PackML state path.

This path had no test at all, which is how it stayed broken. Both statements in
IngestionWorker._process_state were f-strings passed bare to session.execute();
SQLAlchemy 2.x rejects a plain str with ObjectNotExecutableError, and
_handle_message rolls back and re-raises, so *every* state message failed and no
packml_states row was ever written by the worker. The asset-update statement ran
unconditionally, so this was not limited to transitions carrying a previous
state.

Runs against in-memory SQLite. The bug was dialect-independent (the statement
never reached the database), so SQLite is sufficient to lock it — and it also
pins the portability fix, since the old duration arithmetic used a Postgres-only
EXTRACT(EPOCH FROM ...::timestamp).
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Asset, Base, PackMLState
from app.workers.ingestion import IngestionWorker


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _session_factory():
    """In-memory SQLite with only the tables this path touches."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[Asset.__table__, PackMLState.__table__],
        )
    return engine, sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_asset(session: AsyncSession, org_id, asset_id) -> None:
    # workcell_id is NOT NULL since migration 013; the organizations/workcells
    # tables aren't created here and SQLite doesn't enforce FKs by default, so a
    # bare UUID is enough to exercise this path.
    session.add(
        Asset(
            id=asset_id,
            organization_id=org_id,
            workcell_id=uuid4(),
            asset_type_id=uuid4(),
            name="Filler-01",
        )
    )
    await session.commit()


def test_process_state_writes_a_row():
    """The base case that never worked: a state message must persist a row."""

    async def scenario():
        engine, Session = await _session_factory()
        org_id, asset_id = uuid4(), uuid4()
        worker = IngestionWorker()

        async with Session() as session:
            await _seed_asset(session, org_id, asset_id)
            await worker._process_state(
                session,
                str(asset_id),
                {
                    "packml_state": "Execute",
                    "timestamp": "2026-07-19T10:00:00+00:00",
                },
                str(org_id),
            )
            await session.commit()

            states = (await session.execute(select(PackMLState))).scalars().all()
            assert len(states) == 1
            assert states[0].state == "Execute"
            assert states[0].state_exited_at is None

            asset = (await session.execute(select(Asset))).scalars().one()
            assert asset.current_packml_state == "Execute"

        await engine.dispose()

    run(scenario())


def test_process_state_closes_the_previous_state_with_a_duration():
    """A transition must close the open row and compute its duration."""

    async def scenario():
        engine, Session = await _session_factory()
        org_id, asset_id = uuid4(), uuid4()
        entered = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
        worker = IngestionWorker()

        async with Session() as session:
            await _seed_asset(session, org_id, asset_id)
            session.add(
                PackMLState(
                    asset_id=asset_id,
                    state="Execute",
                    state_entered_at=entered,
                )
            )
            await session.commit()

            await worker._process_state(
                session,
                str(asset_id),
                {
                    "packml_state": "Held",
                    "previous_state": "Execute",
                    "timestamp": (entered + timedelta(minutes=5)).isoformat(),
                },
                str(org_id),
            )
            await session.commit()

            closed = (
                await session.execute(
                    select(PackMLState).where(PackMLState.state == "Execute")
                )
            ).scalars().one()
            assert closed.state_exited_at is not None
            assert float(closed.duration_seconds) == pytest.approx(300.0)

            opened = (
                await session.execute(
                    select(PackMLState).where(PackMLState.state == "Held")
                )
            ).scalars().one()
            assert opened.previous_state == "Execute"
            assert opened.state_exited_at is None

        await engine.dispose()

    run(scenario())


def test_process_state_survives_a_naive_stored_timestamp():
    """SQLite reads state_entered_at back naive; subtracting it must not raise.

    Before the aware-coercion this raised TypeError inside the worker, which
    _handle_message converts into a dropped message.
    """

    async def scenario():
        engine, Session = await _session_factory()
        org_id, asset_id = uuid4(), uuid4()
        naive_entered = datetime(2026, 7, 19, 10, 0)
        worker = IngestionWorker()

        async with Session() as session:
            await _seed_asset(session, org_id, asset_id)
            session.add(
                PackMLState(
                    asset_id=asset_id,
                    state="Execute",
                    state_entered_at=naive_entered,
                )
            )
            await session.commit()

            await worker._process_state(
                session,
                str(asset_id),
                {
                    "packml_state": "Held",
                    "previous_state": "Execute",
                    "timestamp": "2026-07-19T10:05:00+00:00",
                },
                str(org_id),
            )
            await session.commit()

            closed = (
                await session.execute(
                    select(PackMLState).where(PackMLState.state == "Execute")
                )
            ).scalars().one()
            assert float(closed.duration_seconds) == pytest.approx(300.0)

        await engine.dispose()

    run(scenario())


def test_process_state_does_not_interpolate_previous_state():
    """`previous_state` is attacker-controlled and was interpolated into SQL.

    It is the only unvalidated value in the statement (asset_id and
    organization_id are UUID-parsed upstream in _handle_message). A quote-laden
    value must be treated as data and simply match nothing.
    """

    async def scenario():
        engine, Session = await _session_factory()
        org_id, asset_id = uuid4(), uuid4()
        worker = IngestionWorker()

        async with Session() as session:
            await _seed_asset(session, org_id, asset_id)
            session.add(
                PackMLState(
                    asset_id=asset_id,
                    state="Execute",
                    state_entered_at=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
                )
            )
            await session.commit()

            await worker._process_state(
                session,
                str(asset_id),
                {
                    "packml_state": "Held",
                    "previous_state": "' OR '1'='1",
                    "timestamp": "2026-07-19T10:05:00+00:00",
                },
                str(org_id),
            )
            await session.commit()

            # The real open row must be untouched — a successful injection
            # would have closed every open state for this asset.
            untouched = (
                await session.execute(
                    select(PackMLState).where(PackMLState.state == "Execute")
                )
            ).scalars().one()
            assert untouched.state_exited_at is None
            assert untouched.duration_seconds is None

        await engine.dispose()

    run(scenario())
