"""Characterization + push-down guard for GET /health/{vehicle_id}.

vehicle_health built the ENTIRE fleet's health aggregation (two unscoped org
queries) and linear-searched it for one vehicle. This pins its exact output for
a populated vehicle and for an unknown one, and asserts the refactor scopes both
queries to the vehicle in SQL instead of scanning the org.

The safety score maps exceptions to a vehicle through the diagnostics device set
(device_id != vehicle_id), with a fallback that treats an exception whose
device_id equals the vehicle_id as that vehicle's. Both paths are seeded here so
the scoped version (device_id IN vehicle_devices ∪ {vehicle_id}) is proven to
match the full-fleet computation exactly.
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
V1, V2 = "VEH-1", "VEH-2"
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
            # VEH-1 on device DEV-1: two active DTCs (one critical) + one resolved
            GeoTabDiagnostic(id=uuid4(), organization_id=ORG, device_id="DEV-1",
                             vehicle_id=V1, status="active", severity="high",
                             dtc_code="P0301", last_seen_at=NOW),
            GeoTabDiagnostic(id=uuid4(), organization_id=ORG, device_id="DEV-1",
                             vehicle_id=V1, status="active", severity="critical",
                             dtc_code="P0128", last_seen_at=NOW),
            GeoTabDiagnostic(id=uuid4(), organization_id=ORG, device_id="DEV-1",
                             vehicle_id=V1, status="resolved", severity="low",
                             dtc_code="P0420", last_seen_at=NOW),
            # VEH-2 on device DEV-2
            GeoTabDiagnostic(id=uuid4(), organization_id=ORG, device_id="DEV-2",
                             vehicle_id=V2, status="active", severity="medium",
                             dtc_code="P0500", last_seen_at=NOW),
        ])
        s.add_all([
            # Two exceptions on DEV-1 -> map to VEH-1
            GeoTabException(id=uuid4(), organization_id=ORG, device_id="DEV-1",
                            exception_type="speeding", timestamp=NOW),
            GeoTabException(id=uuid4(), organization_id=ORG, device_id="DEV-1",
                            exception_type="harsh_braking", timestamp=NOW),
            # One exception whose device_id IS the vehicle_id -> fallback to VEH-1
            GeoTabException(id=uuid4(), organization_id=ORG, device_id=V1,
                            exception_type="speeding", timestamp=NOW),
            # One on DEV-2 -> maps to VEH-2, must NOT count for VEH-1
            GeoTabException(id=uuid4(), organization_id=ORG, device_id="DEV-2",
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
    m = re.search(r"\bwhere\b", sql, flags=re.IGNORECASE)
    return sql[m.start():].lower() if m else ""


def test_populated_vehicle_health_exact_and_scoped():
    async def scenario():
        engine, Session = await _factory_and_seed()
        stmts = _capture(engine)
        async with Session() as s:
            row = await fh.vehicle_health(vehicle_id=V1, org_id=ORG, db=s)
        await engine.dispose()
        return row, stmts

    row, stmts = run(scenario())
    # Exact contract for VEH-1: 2 active DTCs, 3 exceptions map to it
    # (DEV-1 x2 + the device_id==VEH-1 fallback), so safetyScore = 100 - 3*5.
    assert row["vehicleId"] == V1
    assert len(row["dtcs"]) == 2
    assert row["safetyScore"] == 85
    assert row["securityStatus"] == "alert"  # has a critical DTC
    assert row["status"] == "warning"

    # Push-down: diagnostics scoped by vehicle_id, exceptions scoped by device_id
    # — neither is a whole-org scan.
    diag_sql = [s for s in stmts if "geotab_diagnostics" in s.lower()]
    exc_sql = [s for s in stmts if "geotab_exceptions" in s.lower()]
    assert diag_sql and any("vehicle_id" in _where(s) for s in diag_sql), (
        "diagnostics not scoped to the vehicle:\n" + "\n".join(diag_sql)
    )
    assert exc_sql and any("device_id" in _where(s) for s in exc_sql), (
        "exceptions not scoped to the vehicle's devices:\n" + "\n".join(exc_sql)
    )


def test_unknown_vehicle_returns_default():
    async def scenario():
        engine, Session = await _factory_and_seed()
        async with Session() as s:
            row = await fh.vehicle_health(vehicle_id="VEH-NONE", org_id=ORG, db=s)
        await engine.dispose()
        return row

    row = run(scenario())
    assert row["vehicleId"] == "VEH-NONE"
    assert row["dtcs"] == []
    assert row["safetyScore"] == 100
    assert row["securityStatus"] == "secure"
    assert row["status"] == "online"
