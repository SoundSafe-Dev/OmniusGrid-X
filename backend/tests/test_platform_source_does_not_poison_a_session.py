"""Adding a platform data source must not break the session forever (FS-418).

`POST /api/v1/nlp/platform/sessions/{id}/sources` attaches a platform-wide source — the ERP,
the yard — to an analysis session. It set `source_id` from
`params["asset_id"] or params["id"] or source_type`, and a platform-wide source has neither
id, so the fallback wrote the literal string `"erp"` or `"yard"` into a column every consumer
reads as a uuid.

`DataSourceResponse.source_id` is `Optional[UUID]`. So from that moment
`GET /api/v1/nlp/sessions/{id}/data` raised a validation error and returned **500 for that
session permanently**, and the data-sources panel on the Correlation AI page never loaded
again.

ONE CLICK, NO ERROR AT THE POINT OF THE CLICK, AND THE SESSION IS UNUSABLE. The POST returns
201 happily; the damage only shows the next time the panel is opened, which is a different
action, often in a different visit.

WHY IT SURVIVED. The same fallback existed in `scripts/seed_demo_data.py`, and when it was
fixed there the conclusion recorded was "the API itself cannot produce this — its own request
model rejects a non-uuid, so the seed was the only writer". That was wrong: this endpoint
does not go through `AddDataSourceRequest`, it constructs the row directly. The seed fix
removed the evidence without removing the cause, and it took clicking through a live session
to find the rest of it.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AnalysisSession, Base, Organization, SessionDataSource, User
from tests._sqlite import create_all, minimal_organization, minimal_user, sqlite_engine

pytestmark = pytest.mark.asyncio

ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000005")
USER_ID = str(uuid.uuid4())
SESSION_ID = str(uuid.uuid4())


@pytest_asyncio.fixture
async def client():
    engine = sqlite_engine()
    await create_all(engine, Base.metadata, [
        Organization.__table__, User.__table__,
        AnalysisSession.__table__, SessionDataSource.__table__,
    ])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(minimal_organization(ORG_ID))
        await session.flush()
        session.add(minimal_user(USER_ID, ORG_ID))
        await session.flush()
        session.add(AnalysisSession(id=SESSION_ID, user_id=USER_ID,
                                    organization_id=str(ORG_ID), title="T", status="active"))
        await session.commit()

    from app.api.auth import get_current_active_user
    from app.core.tenant import get_tenant_db, get_tenant_org_id
    from app.db.database import get_db
    from app.main import app as fastapi_app

    async def _session():
        async with maker() as s:
            yield s

    class _User:
        id = USER_ID
        organization_id = ORG_ID
        role = "admin"
        email = "op@test.local"
        is_active = True

    overrides = dict(fastapi_app.dependency_overrides)
    fastapi_app.dependency_overrides[get_db] = _session
    fastapi_app.dependency_overrides[get_tenant_db] = _session
    fastapi_app.dependency_overrides[get_tenant_org_id] = lambda: ORG_ID
    fastapi_app.dependency_overrides[get_current_active_user] = lambda: _User()
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as c:
        yield c
    fastapi_app.dependency_overrides = overrides


async def _add_source(session, source_type: str, source_id):
    """Write the row the endpoint writes, without needing the platform providers to run.

    The providers reach for telemetry, ERP entities and yard rows that this fixture has no
    reason to create; the defect is in what the endpoint STORES, so the row is stored
    directly and read back through the real response model.
    """
    session.add(SessionDataSource(
        id=str(uuid.uuid4()), session_id=SESSION_ID, source_type=source_type,
        source_id=source_id, file_name=f"{source_type}.xlsx", data_type="spreadsheet",
        processed_data={}, meta_data={"platform_source": True},
    ))
    await session.commit()


class TestTheHelperThatDecidesSourceId:
    """Unit-level, because the fix is one function and it is the whole fix."""

    def test_a_platform_wide_source_has_no_row_id(self):
        from app.api.platform_correlation import _source_row_id

        # The ERP as a whole. There is no row this came from.
        assert _source_row_id({}) is None
        assert _source_row_id({"tab": "PurchaseOrders"}) is None

    def test_an_asset_scoped_source_keeps_its_id(self):
        from app.api.platform_correlation import _source_row_id

        asset_id = str(uuid.uuid4())
        assert _source_row_id({"asset_id": asset_id}) == asset_id

    def test_it_never_falls_back_to_the_source_type(self):
        """The regression itself. `"erp"` in a uuid column is what broke the session."""
        from app.api.platform_correlation import _source_row_id

        for params in ({}, {"asset_id": None}, {"id": ""}):
            assert _source_row_id(params) != "erp"
            assert _source_row_id(params) is None


class TestTheSessionStaysReadable:
    async def test_a_platform_source_with_no_row_id_reads_back(self, client, request):
        maker = None
        # Reach the sessionmaker the fixture built, to write the row the endpoint writes.
        from app.db.database import get_db
        from app.main import app as fastapi_app

        gen = fastapi_app.dependency_overrides[get_db]()
        session = await gen.__anext__()
        await _add_source(session, "erp", None)

        response = await client.get(f"/api/v1/nlp/sessions/{SESSION_ID}/data")
        assert response.status_code == 200, response.text
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["source_type"] == "erp"
        assert rows[0]["source_id"] is None

    async def test_a_non_uuid_source_id_is_what_used_to_break_it(self, client):
        """Pins the failure mode, so the reason for the None above cannot be forgotten.

        With `"erp"` stored, the transcript endpoint cannot serialise the row at all — it is
        a 500, not a degraded field, and it takes the whole panel with it.
        """
        from app.db.database import get_db
        from app.main import app as fastapi_app

        gen = fastapi_app.dependency_overrides[get_db]()
        session = await gen.__anext__()
        await _add_source(session, "erp", "erp")

        response = await client.get(f"/api/v1/nlp/sessions/{SESSION_ID}/data")
        assert response.status_code == 500, (
            "if this ever returns 200, the response model stopped declaring source_id as a "
            "UUID — in which case the fix above is no longer load-bearing and this file "
            "should be revisited rather than deleted"
        )
