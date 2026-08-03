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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [
        Organization.__table__, Workcell.__table__,
        AssetType.__table__, Asset.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
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
