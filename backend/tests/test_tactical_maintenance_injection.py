"""Security guard: TacticalEngine._is_maintenance_mode must not be SQL-injectable.

The method built `WHERE id = '{asset_id}'` by f-string, and asset_id flows from
the feature vector (edge/ingestion data). A value like `' OR '1'='1` matched
every row. It also queried assets.maintenance_mode, a column that does not exist
in the schema — so on a real DB the method errored; the fix parameterizes the
value and fails safe.
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
        await conn.execute(text("INSERT INTO assets VALUES ('a1', 1), ('a2', 0)"))
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
        # a1 is in maintenance, a2 is not — parameterized lookups are correct.
        assert bool(await eng._is_maintenance_mode("a1")) is True
        assert bool(await eng._is_maintenance_mode("a2")) is False
        # The classic injection: on the old f-string code this became
        # WHERE id = '' OR '1'='1' -> matched a1 -> truthy. Parameterized, it is a
        # literal id that matches no row -> falsy.
        injected = await eng._is_maintenance_mode("' OR '1'='1")
        assert not injected, "SQL injection still changes the result"
        await engine.dispose()

    run(scenario())
