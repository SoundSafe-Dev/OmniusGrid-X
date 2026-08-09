"""Security guard: TacticalEngine._is_maintenance_mode must not be SQL-injectable.

The method built `WHERE id = '{asset_id}'` by f-string, and asset_id flows from
the feature vector (edge/ingestion data). A value like `' OR '1'='1` matched
every row. It also queried assets.maintenance_mode, a column that did not exist
in the schema — so on a real DB the method errored; the fix parameterizes the
value and fails safe. Migration 053 has since added the column, and the method
now distinguishes "no readable row" (suppress) from "the row says false".

THAT CHANGED WHAT THIS TEST HAS TO ASSERT. An id matching nothing no longer
returns falsy, so `assert not injected` would now hold for an injection that
worked as well as one that failed. The fixture is inverted instead: the FIRST
row is not in maintenance, so an injection that matched it returns False and a
parameterized lookup that matched nothing returns True. The two outcomes are
distinguishable again, which is the only reason the assertion means anything.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.db.database as db_module


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _install_assets_table():
    """Point the module's AsyncSessionLocal at a SQLite assets table that
    actually HAS a maintenance_mode column, so injection changing the result is
    observable. The method does `from app.db.database import AsyncSessionLocal`
    at call time, so patching that module attribute is what takes effect."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE assets (id TEXT PRIMARY KEY, maintenance_mode INTEGER)"
        ))
        await conn.execute(text("INSERT INTO assets VALUES ('a1', 0), ('a2', 1)"))
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def _factory():
        return Session()

    db_module.AsyncSessionLocal = _factory
    return engine


def test_injection_string_matches_nothing():
    from app.services.tactical_engine import LocalTacticalEngine

    async def scenario():
        engine = await _install_assets_table()
        eng = LocalTacticalEngine()
        # a1 is NOT in maintenance, a2 is. Both are read correctly, which is also the
        # control for everything below: without it, every `is True` here is satisfied by
        # the except branch, which returns True for a database that never answered.
        assert await eng._is_maintenance_mode("a1") is False
        assert await eng._is_maintenance_mode("a2") is True
        # The classic injection: on the old f-string code this became
        # WHERE id = '' OR '1'='1' -> matched a1 -> False, a1's own value. Parameterized,
        # it is a literal id matching no row -> True, the suppression.
        injected = await eng._is_maintenance_mode("' OR '1'='1")
        assert injected is True, (
            "SQL injection still changes the result: the predicate matched a1 and "
            "returned another asset's maintenance state"
        )
        await engine.dispose()

    run(scenario())
