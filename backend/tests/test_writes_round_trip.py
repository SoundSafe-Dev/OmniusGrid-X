"""A write must survive the round trip (FS-401).

WHAT WAS NOT COVERED. `test_write_endpoints_reject_cleanly_realdb.py` asserts that a POST
with an empty body answers 422 rather than 5xx. That is VALIDATION, not function: an
endpoint that rejects rubbish correctly and then silently drops a good write passes it
without complaint. Nothing anywhere asserted that a created row can be read back, or that
an update changes what a later GET returns.

That gap is not theoretical in this repository. `POST /api/v1/user/goals` raised
`TypeError` on every call it ever received and was found by the contract gate rather than
by a test; `POST /engines/strategic/.../approve` returned 422 to every click for its whole
life because the client sent a body where the server declared query parameters. Both are
"the write path was never exercised".

WHY IN-MEMORY SQLITE. The real-DB fixtures are gated on `pytest.importorskip
("testcontainers")` and skip wherever Docker is absent, which is most developer machines
and was the case for the whole session that wrote this. A test that only runs in CI does
not stop you shipping a broken write at 2am. Only the tables this path touches are created,
because a whole-metadata `create_all` fails on a Postgres ARRAY column elsewhere in the
model.

WHAT THIS DELIBERATELY DOES NOT PROVE. Tenant isolation. SQLite has no row-level security,
so every RLS claim belongs to the real-DB suite and none is made here. What is checked is
narrower and was untested: the value goes in, comes back, and changes when updated.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests._sqlite import create_all, sqlite_engine

from app.db.models import Asset, AssetType, Base, Organization, Workcell

pytestmark = pytest.mark.asyncio

ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture
async def api():
    """The real app, bound to an in-memory database, with the tenant seams overridden."""
    from app.api.assets import get_current_active_user
    from app.core.tenant import get_tenant_db, get_tenant_org_id
    from app.db.database import get_db
    from app.main import app as fastapi_app

    # FK-enforcing; see tests/_sqlite.py.
    engine = sqlite_engine()
    tables = [
        Organization.__table__, Workcell.__table__,
        AssetType.__table__, Asset.__table__,
    ]
    await create_all(engine, Base.metadata, tables)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    # Seed the rows the create path's foreign keys need.
    workcell_id, asset_type_id = uuid.uuid4(), uuid.uuid4()
    async with maker() as session:
        session.add(Organization(id=ORG_ID, name="QA Org", slug="qa-org"))
        session.add(Workcell(id=workcell_id, organization_id=ORG_ID, name="QA Cell"))
        session.add(AssetType(id=asset_type_id, name="QA Type", category="machine"))
        await session.commit()

    async def _session():
        async with maker() as session:
            yield session

    class _User:
        id = uuid.uuid4()
        organization_id = ORG_ID
        role = "admin"
        email = "qa@test.local"
        is_active = True

    overrides = dict(fastapi_app.dependency_overrides)
    fastapi_app.dependency_overrides[get_db] = _session
    fastapi_app.dependency_overrides[get_tenant_db] = _session
    fastapi_app.dependency_overrides[get_tenant_org_id] = lambda: ORG_ID
    fastapi_app.dependency_overrides[get_current_active_user] = lambda: _User()

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as client:
        client.workcell_id = str(workcell_id)      # type: ignore[attr-defined]
        client.asset_type_id = str(asset_type_id)  # type: ignore[attr-defined]
        yield client

    fastapi_app.dependency_overrides = overrides
    await engine.dispose()


def _payload(client, name):
    return {
        "name": name,
        "organization_id": str(ORG_ID),
        "workcell_id": client.workcell_id,
        "asset_type_id": client.asset_type_id,
        "vendor": "QA",
        "model": "T-1000",
    }


class TestAnAssetSurvivesTheRoundTrip:
    async def test_create_returns_the_row_it_made(self, api):
        response = await api.post("/api/v1/assets/", json=_payload(api, "Round Trip A"))
        assert response.status_code in (200, 201), response.text
        body = response.json()
        assert body["name"] == "Round Trip A"
        assert body["id"]

    async def test_a_created_asset_can_be_read_back(self, api):
        """The assertion the validation walk cannot make. A handler that answers 200 and
        commits nothing passes every test in this repository except this one."""
        created = (await api.post("/api/v1/assets/", json=_payload(api, "Round Trip B"))).json()
        response = await api.get(f"/api/v1/assets/{created['id']}")
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Round Trip B"

    async def test_it_appears_in_the_list(self, api):
        """Read-back by id and appearing in the list are different queries — the second is
        the one a page actually uses, and the one a tenant filter can silently empty."""
        await api.post("/api/v1/assets/", json=_payload(api, "Round Trip C"))
        body = (await api.get("/api/v1/assets/")).json()
        rows = body.get("items", body)
        assert any(r["name"] == "Round Trip C" for r in rows), rows

    async def test_an_update_changes_what_a_later_get_returns(self, api):
        """Not "the PUT returned 200" — what the NEXT reader sees. A handler that echoes
        the request back without committing satisfies the weaker check."""
        created = (await api.post("/api/v1/assets/", json=_payload(api, "Before"))).json()
        update = await api.put(f"/api/v1/assets/{created['id']}", json={"name": "After"})
        assert update.status_code == 200, update.text

        reread = await api.get(f"/api/v1/assets/{created['id']}")
        assert reread.json()["name"] == "After"

    async def test_an_unset_field_is_not_wiped_by_a_partial_update(self, api):
        """A PUT carrying one field must not blank the others. `model_dump()` without
        `exclude_unset` turns every omitted field into an explicit None, which is a silent
        data-loss shape rather than an error."""
        created = (await api.post("/api/v1/assets/", json=_payload(api, "Keeps Vendor"))).json()
        await api.put(f"/api/v1/assets/{created['id']}", json={"name": "Renamed"})
        body = (await api.get(f"/api/v1/assets/{created['id']}")).json()
        assert body["name"] == "Renamed"
        assert body["vendor"] == "QA", "a partial update wiped a field it did not mention"


class TestTheHarnessIsHonest:
    async def test_a_missing_asset_is_a_404_not_an_empty_row(self, api):
        """Control. If every GET answered 200 with something, the round-trip assertions
        above would pass against a stub."""
        response = await api.get(f"/api/v1/assets/{uuid.uuid4()}")
        assert response.status_code == 404, response.text

    async def test_an_invalid_payload_is_still_rejected(self, api):
        """The other control: these overrides must not have disabled validation."""
        response = await api.post("/api/v1/assets/", json={})
        assert response.status_code == 422, response.text


@pytest_asyncio.fixture
async def alarm_api():
    """Same arrangement, with the alarm tables. Separate fixture because the alarm path
    needs an asset row and the asset path does not need alarms — a single fixture creating
    everything would hide which tables each endpoint actually touches."""
    from app.api.assets import get_current_active_user
    from app.core.tenant import get_tenant_db, get_tenant_org_id
    from app.db.database import get_db
    from app.db.models import Alarm
    from app.main import app as fastapi_app

    # FK-enforcing; see tests/_sqlite.py.
    engine = sqlite_engine()
    tables = [
        Organization.__table__, Workcell.__table__, AssetType.__table__,
        Asset.__table__, Alarm.__table__,
    ]
    await create_all(engine, Base.metadata, tables)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    asset_id = uuid.uuid4()
    alarm_id = uuid.uuid4()
    async with maker() as session:
        wc, at = uuid.uuid4(), uuid.uuid4()
        session.add(Organization(id=ORG_ID, name="QA Org", slug="qa-org"))
        session.add(Workcell(id=wc, organization_id=ORG_ID, name="QA Cell"))
        session.add(AssetType(id=at, name="QA Type", category="machine"))
        session.add(Asset(id=asset_id, organization_id=ORG_ID, workcell_id=wc,
                          asset_type_id=at, name="QA Asset"))
        session.add(Alarm(
            id=alarm_id, organization_id=ORG_ID, asset_id=asset_id,
            alarm_code="QA-001", severity="critical", message="QA alarm",
            occurred_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            is_active=True, is_acknowledged=False,
        ))
        await session.commit()

    async def _session():
        async with maker() as session:
            yield session

    class _User:
        id = uuid.uuid4()
        organization_id = ORG_ID
        role = "admin"
        email = "qa@test.local"
        is_active = True

    overrides = dict(fastapi_app.dependency_overrides)
    fastapi_app.dependency_overrides[get_db] = _session
    fastapi_app.dependency_overrides[get_tenant_db] = _session
    fastapi_app.dependency_overrides[get_tenant_org_id] = lambda: ORG_ID
    fastapi_app.dependency_overrides[get_current_active_user] = lambda: _User()

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as client:
        client.alarm_id = str(alarm_id)  # type: ignore[attr-defined]
        yield client

    fastapi_app.dependency_overrides = overrides
    await engine.dispose()


class TestAcknowledgingAnAlarmSticks:
    """The write that MATTERS most on this surface: an operator acknowledging an alarm is
    saying "I have seen this". If it does not persist, the alarm reappears and the record of
    who responded is gone — and the endpoint answering 200 looks identical either way."""

    async def test_acknowledge_persists(self, alarm_api):
        response = await alarm_api.post(f"/api/v1/alarms/{alarm_api.alarm_id}/acknowledge", json={})
        assert response.status_code in (200, 204), response.text

        reread = await alarm_api.get(f"/api/v1/alarms/{alarm_api.alarm_id}")
        assert reread.status_code == 200, reread.text
        assert reread.json()["is_acknowledged"] is True

    async def test_acknowledging_twice_is_refused_not_silently_repeated(self, alarm_api):
        """A second acknowledgement must not overwrite who acknowledged it first. The
        endpoint answers 400 'Alarm already acknowledged', which is the behaviour that
        keeps the first responder's name on the record."""
        await alarm_api.post(f"/api/v1/alarms/{alarm_api.alarm_id}/acknowledge", json={})
        second = await alarm_api.post(f"/api/v1/alarms/{alarm_api.alarm_id}/acknowledge", json={})
        assert second.status_code == 400, second.text
        assert "already acknowledged" in second.text.lower()

    async def test_an_unacknowledged_alarm_starts_unacknowledged(self, alarm_api):
        """Control: the fixture must not hand the test an already-acknowledged alarm, or
        the assertions above would pass against an endpoint that does nothing."""
        body = (await alarm_api.get(f"/api/v1/alarms/{alarm_api.alarm_id}")).json()
        assert body["is_acknowledged"] is False


# ---------------------------------------------------------------------------------------
# FS-404: an endpoint whose path says "vehicle" and whose filter meant "device".
#
# Three identifier spaces live in the fleet subsystem and none is interchangeable:
#
#     vehicles.id                    3ca4146e-…    (UUID)
#     geotab_diagnostics.vehicle_id  TRK-114       (the vehicle number)
#     geotab_*.device_id             gt-device-001
#
# `GET /fleet/vehicles/{vehicle_id}/security` passed its path parameter straight through as
# a device id. `GET /fleet/health` — the list a UI renders and picks a row from — publishes
# `vehicleId: TRK-114`, so the only identifier a caller HAS returned nothing, and the only
# one that worked is exposed by no endpoint at all. Measured before the fix: UUID -> 0,
# TRK-114 -> 0, gt-device-001 -> 2.
#
# Kept in this file because it is the same question as the round trips above — does the
# thing a caller can actually do produce the thing it promises — and it needs the same
# no-Docker fixture.
# ---------------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fleet_api():
    from app.api.assets import get_current_active_user
    from app.core.tenant import get_tenant_db, get_tenant_org_id
    from app.db.database import get_db
    from app.db.models import GeoTabDiagnostic, GeoTabException
    from app.main import app as fastapi_app

    # FK-enforcing; see tests/_sqlite.py.
    engine = sqlite_engine()
    tables = [
        Organization.__table__, GeoTabDiagnostic.__table__, GeoTabException.__table__,
    ]
    await create_all(engine, Base.metadata, tables)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        session.add(Organization(id=ORG_ID, name="QA Org", slug="qa-org"))
        # The bridge row: this is the ONLY table carrying both identifiers.
        session.add(GeoTabDiagnostic(
            organization_id=ORG_ID, device_id="gt-device-001", vehicle_id="TRK-114",
            dtc_code="P0300", severity="critical", status="active",
        ))
        session.add(GeoTabException(
            organization_id=ORG_ID, device_id="gt-device-001",
            exception_type="speeding", severity="high",
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        ))
        await session.commit()

    async def _session():
        async with maker() as session:
            yield session

    class _User:
        id = uuid.uuid4()
        organization_id = ORG_ID
        role = "admin"
        email = "qa@test.local"
        is_active = True

    overrides = dict(fastapi_app.dependency_overrides)
    fastapi_app.dependency_overrides[get_db] = _session
    fastapi_app.dependency_overrides[get_tenant_db] = _session
    fastapi_app.dependency_overrides[get_tenant_org_id] = lambda: ORG_ID
    fastapi_app.dependency_overrides[get_current_active_user] = lambda: _User()

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as client:
        yield client

    fastapi_app.dependency_overrides = overrides
    await engine.dispose()


class TestSecurityEventsAnswerTheIdentifierCallersHave:
    async def test_the_vehicle_id_the_fleet_list_publishes_works(self, fleet_api):
        """THE ASSERTION THIS EXISTS FOR. `TRK-114` is what `/fleet/health` hands a client;
        before the fix this returned an empty list, which reads as 'this vehicle has no
        security events' rather than 'you asked in the wrong vocabulary'."""
        response = await fleet_api.get("/api/v1/fleet/vehicles/TRK-114/security")
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1, response.json()

    async def test_a_device_id_still_works(self, fleet_api):
        """Backwards compatibility, deliberately. It is the identifier this endpoint has
        always accepted, and rejecting it would break anyone who worked out the trick."""
        response = await fleet_api.get("/api/v1/fleet/vehicles/gt-device-001/security")
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1

    async def test_an_unknown_identifier_returns_nothing_rather_than_everything(self, fleet_api):
        """The control. Resolving "anything I cannot map" to "all devices" would make both
        assertions above pass while turning a per-vehicle endpoint into a fleet-wide one."""
        response = await fleet_api.get("/api/v1/fleet/vehicles/NOT-A-VEHICLE/security")
        assert response.status_code == 200, response.text
        assert response.json() == []
