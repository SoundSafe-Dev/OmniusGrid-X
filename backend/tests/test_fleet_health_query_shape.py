"""Characterization + push-down guard for the vehicle-scoped fleet_health endpoints.

/vehicles/{id}/dtcs and /vehicles/{id}/security loaded the whole org's
diagnostics/exceptions and filtered to one vehicle in Python. This pins their
exact output and asserts the vehicle/device filter is now applied in the SQL
WHERE (so the DB returns one vehicle's rows, not the org's) rather than in
Python.

In-memory SQLite: the helpers take a session and org_id and read one table each;
no live services. The endpoints' own auth/tenant dependencies are bypassed by
calling the route functions directly with a seeded session and org_id.
"""

import asyncio
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api import fleet_health as fh
from app.db.models import Base, GeoTabDiagnostic, GeoTabException


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


ORG = uuid4()
TARGET = "VEH-1"
OTHER = "VEH-2"
NOW = datetime(2026, 7, 1, tzinfo=timezone.utc)


async def _factory_and_seed():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[GeoTabDiagnostic.__table__, GeoTabException.__table__],
        )
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as s:
        s.add_all([
            GeoTabDiagnostic(id=uuid4(), organization_id=ORG, device_id="DEV-1",
                             vehicle_id=TARGET, status="active", severity="high",
                             dtc_code="P0301", last_seen_at=NOW),
            GeoTabDiagnostic(id=uuid4(), organization_id=ORG, device_id="DEV-1",
                             vehicle_id=TARGET, status="active", severity="low",
                             dtc_code="P0420", last_seen_at=NOW),
            GeoTabDiagnostic(id=uuid4(), organization_id=ORG, device_id="DEV-2",
                             vehicle_id=OTHER, status="active", severity="critical",
                             dtc_code="P0128", last_seen_at=NOW),
            # inactive on the target vehicle: _active_diagnostics filters status
            GeoTabDiagnostic(id=uuid4(), organization_id=ORG, device_id="DEV-1",
                             vehicle_id=TARGET, status="resolved", severity="high",
                             dtc_code="P0500", last_seen_at=NOW),
        ])
        s.add_all([
            GeoTabException(id=uuid4(), organization_id=ORG, device_id=TARGET,
                            exception_type="speeding", timestamp=NOW),
            GeoTabException(id=uuid4(), organization_id=ORG, device_id=TARGET,
                            exception_type="harsh_braking", timestamp=NOW),
            GeoTabException(id=uuid4(), organization_id=ORG, device_id=OTHER,
                            exception_type="speeding", timestamp=NOW),
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


def _where(sql: str) -> str:
    """The WHERE portion only. The column name appears in the SELECT list of a
    `SELECT *`-style ORM query regardless of filtering, so a push-down check has
    to look after WHERE, not at the whole statement. SQLAlchemy formats the
    keyword as `\\nWHERE`, so match it whitespace-agnostically."""
    m = re.search(r"\bwhere\b", sql, flags=re.IGNORECASE)
    return sql[m.start():].lower() if m else ""


def test_vehicle_dtcs_returns_only_target_and_filters_in_sql():
    async def scenario():
        engine, Session = await _factory_and_seed()
        stmts = _capture(engine)
        async with Session() as s:
            out = await fh.vehicle_dtcs(vehicle_id=TARGET, org_id=ORG, db=s)
        await engine.dispose()
        return out, stmts

    out, stmts = run(scenario())
    # Behavior: only the target vehicle's TWO active DTCs (resolved one excluded).
    codes = sorted(d["code"] for d in out)
    assert codes == ["P0301", "P0420"], codes
    # Push-down: the diagnostics SELECT filters on vehicle_id in SQL.
    diag_sql = [s for s in stmts if "geotab_diagnostics" in s.lower()]
    assert diag_sql, "no diagnostics query issued"
    assert any("vehicle_id" in _where(s) for s in diag_sql), (
        "vehicle filter not pushed to SQL — still scanning the whole org:\n"
        + "\n".join(diag_sql)
    )


def test_vehicle_security_returns_only_target_and_filters_in_sql():
    async def scenario():
        engine, Session = await _factory_and_seed()
        stmts = _capture(engine)
        async with Session() as s:
            out = await fh.vehicle_security(vehicle_id=TARGET, org_id=ORG, db=s)
        await engine.dispose()
        return out, stmts

    out, stmts = run(scenario())
    # Behavior: only the target device's TWO exceptions.
    assert len(out) == 2, out
    exc_sql = [s for s in stmts if "geotab_exceptions" in s.lower()]
    assert exc_sql, "no exceptions query issued"
    assert any("device_id" in _where(s) for s in exc_sql), (
        "device filter not pushed to SQL — still scanning the whole org:\n"
        + "\n".join(exc_sql)
    )
