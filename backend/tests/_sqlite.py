"""An in-memory SQLite engine that ENFORCES foreign keys (FS-410).

SQLite ships with `PRAGMA foreign_keys=OFF`. Every in-memory test in this suite therefore
inserts rows in whatever order it likes, against whatever parent rows it did not bother to
create, and passes. Real Postgres rejects both.

THAT IS NOT HYPOTHETICAL. `scripts/seed_demo_data.py` — the path `docs/DEMO.md` tells
operators to run — died on a foreign key the first time it met a fresh database, because
SQLAlchemy's unit of work orders inserts from `relationship()` and 62 of the 69 FK-carrying
models declare only the column. Nothing in 3,200 tests could see it.

MEASURED COST OF TURNING IT ON EVERYWHERE: 76 of 3,210 tests fail (2.4%), spread across
about fifteen files in several people's lanes. That is a cross-lane cleanup rather than a
sprint, so this helper is opt-in — a test module that uses it gets referential integrity
today, and the rest can be converted as their owners reach them.

WHAT IT CATCHES IN PRACTICE. Mostly incomplete fixtures: a table built with
`create_all(tables=[...])` whose FK targets are missing, or a row pointing at a parent
nobody inserted. Both are cases where the test is asserting against a schema laxer than the
one production runs, which is precisely when a green test means least.
"""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def _enforce(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection, _record):  # pragma: no cover - trivial
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def sqlite_engine(**kwargs) -> AsyncEngine:
    """An `sqlite+aiosqlite:///:memory:` engine with FK enforcement switched on.

    Use in place of `create_async_engine("sqlite+aiosqlite:///:memory:")`. If a fixture starts
    failing after the swap, the fixture was relying on SQLite's laxity — the fix is to create
    the missing parent table or row, not to go back.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", **kwargs)
    _enforce(engine.sync_engine)
    return engine


async def create_all(engine: AsyncEngine, metadata, tables: Optional[Iterable] = None) -> None:
    """`metadata.create_all` over an explicit table list, in dependency order.

    Passing `tables=` to `create_all` does NOT pull in the tables those tables reference, so a
    subset that names a child without its parent produces a schema whose FKs point at nothing.
    With enforcement on, SQLite then refuses every insert into that child. This closes over
    the referenced tables so the caller lists what it cares about and gets what it needs.
    """
    resolved = list(tables) if tables is not None else list(metadata.tables.values())
    seen = {t.name for t in resolved}
    frontier = list(resolved)
    while frontier:
        table = frontier.pop()
        for fk in table.foreign_keys:
            parent = fk.column.table
            if parent.name not in seen:
                seen.add(parent.name)
                resolved.append(parent)
                frontier.append(parent)

    ordered = [t for t in metadata.sorted_tables if t.name in seen]
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all, tables=ordered)
