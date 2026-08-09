"""End to end: live Dataverse -> the real sync -> RLS-protected rows in Postgres.

THE GAP THIS CLOSES. Everything else proves one link. The connector tests prove we
build a correct request; the sandbox tests prove a real vendor accepts it; the
real-DB tests prove tenant isolation on hand-written rows. Nothing proved the
*whole* path: that data fetched from a live ERP actually lands in this database,
scoped to the right tenant and invisible to every other one.

WHY IT HAS TO BE POSTGRES, AND WHY THE ROLE MATTERS. Every `erp_*` table carries

    FOR ALL USING (organization_id = NULLIF(
        current_setting('app.current_org_id', true), '')::uuid)

and Postgres applies a FOR ALL policy's USING clause as the INSERT check when no
WITH CHECK is given. With the GUC unset that predicate is NULL and every insert is
rejected.

`run_erp_sync` is a background task with no request to derive the tenant from, and it
opened a raw session — so it set no GUC. That went unnoticed because no ERP table has
`FORCE ROW LEVEL SECURITY` and the development connection owns them, and **owners
bypass RLS**. On any deployment where the application connects as a non-owner role,
this sync wrote nothing while reporting success.

The `tenant_user` fixture role is `NOSUPERUSER NOBYPASSRLS` and does not own the
tables, which is what makes these assertions mean anything. Run as the owner, they
would all pass with the bug present.

WHAT REMOVING THE GUC ACTUALLY DOES, measured by mutation:

    {'error': 'integration not found'}

Not a write failure — the sync's own SELECT of `integration_configurations` is hidden
by RLS, so it gives up before fetching anything and reports that the integration does
not exist. For an integration plainly visible in the UI. Whoever debugged that would
go looking for a deleted configuration, not for a missing GUC.

A NOTE ON HOW THIS TEST WAS NEARLY USELESS. The first version passed against a
deliberately broken sync. `set_config(..., false)` is SESSION-scoped, so the setup
helper's tenant context survived on the pooled connection and was silently inherited
by the code under test — the leak was doing the work, not the sync. The helpers now
clear the GUC after themselves, which is the same reason production `get_tenant_db`
clears it in a `finally`. A test that shares connection state with its subject proves
whatever the state says.

REQUIREMENTS: Docker (testcontainers Postgres) and live Dataverse credentials. Skips
without the credentials; see docs/erp/dynamics-dataverse-setup.md.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select, text

from app.db.models import ERPEntity, ERPSyncStatus, IntegrationConfiguration

ORG = os.environ.get("DATAVERSE_ORG")
TENANT_ID = os.environ.get("DATAVERSE_TENANT_ID")
CLIENT_ID = os.environ.get("DATAVERSE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("DATAVERSE_CLIENT_SECRET")

pytestmark = pytest.mark.skipif(
    not all([ORG, TENANT_ID, CLIENT_ID, CLIENT_SECRET]),
    reason=(
        "needs live Dataverse credentials: DATAVERSE_ORG, DATAVERSE_TENANT_ID, "
        "DATAVERSE_CLIENT_ID, DATAVERSE_CLIENT_SECRET "
        "(see docs/erp/dynamics-dataverse-setup.md)"
    ),
)

#: Present in every Dataverse environment and readable by anything that can
#: authenticate. Also small, so the sync stays quick.
ENTITY_SET = "systemusers"


async def _clear_guc(db) -> None:
    """Reset the session-scoped tenant GUC.

    `set_config(..., false)` is SESSION-scoped: it outlives the SQLAlchemy session and
    stays on the pooled connection for whoever checks it out next. Leaving it set lets
    a test's own setup grant tenant context to the code under test.
    """
    await db.execute(text("SELECT set_config('app.current_org_id', '', false)"))
    await db.commit()


async def _make_integration(session_maker, organization_id: str) -> str:
    """Insert an ERP integration owned by `organization_id`.

    Written through a session with the GUC set, because the insert is subject to the
    same RLS the sync is.
    """
    integration_id = str(uuid.uuid4())
    async with session_maker() as db:
        await db.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(organization_id)},
        )
        # NOTE: `false` here is SESSION-scoped, so this value survives on the
        # pooled connection after the session closes.
        db.add(
            IntegrationConfiguration(
                id=integration_id,
                integration_type="erp",
                integration_name="e2e-dataverse",
                organization_id=organization_id,
                erp_type="dynamics",
                is_active=True,
                configuration={
                    "erp_type": "dynamics",
                    "auth_type": "oauth2",
                    "environment": ORG,
                    "api_type": "dataverse",
                    "auth_config": {
                        "tenant_id": TENANT_ID,
                        "client_id": CLIENT_ID,
                        "client_secret": CLIENT_SECRET,
                    },
                },
                authentication={
                    "tenant_id": TENANT_ID,
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
            )
        )
        await db.commit()
        # RESET IT. Without this the setup contaminates the very thing under test:
        # the next checkout of this pooled connection inherits the GUC, so
        # `run_erp_sync` would appear to work even with no tenant context of its own.
        # This test was written without the reset and passed against a deliberately
        # broken sync — the leak, not the sync, was doing the work.
        #
        # It is also exactly why production `get_tenant_db` clears the GUC in a
        # `finally`: a session-scoped setting outlives the request that set it.
        await _clear_guc(db)
    return integration_id


async def _rows_visible_to(session_maker, organization_id: str, integration_id: str):
    """Read `erp_entities` as `organization_id` sees them — through RLS."""
    async with session_maker() as db:
        await db.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"),
            {"org": str(organization_id)},
        )
        result = await db.execute(
            select(ERPEntity).where(ERPEntity.integration_id == integration_id)
        )
        rows = list(result.scalars().all())
        await _clear_guc(db)
        return rows


@pytest.fixture
async def session_maker(app):
    """The test session maker the `app` fixture bound into every module.

    `run_erp_sync` resolves `AsyncSessionLocal` from `app.db.database` at call time,
    which the fixture rebinds, so the sync runs against this container.
    """
    from app.db import database as db_module

    return db_module.AsyncSessionLocal


class TestLiveErpSyncLandsTenantScopedRows:
    async def test_real_dataverse_records_reach_the_database(
        self, session_maker, seeded_orgs
    ):
        """THE WHOLE PATH IN ONE ASSERTION: live Microsoft data in our Postgres."""
        from app.api.erp_integrations import run_erp_sync

        org_a = str(seeded_orgs["org_a_id"])
        integration_id = await _make_integration(session_maker, org_a)

        summary = await run_erp_sync(integration_id, org_a, [ENTITY_SET])

        assert ENTITY_SET in summary, summary
        assert summary[ENTITY_SET]["status"] == "success", summary
        assert summary[ENTITY_SET]["records_synced"] > 0, (
            f"the sync reported success with zero rows: {summary}"
        )

        rows = await _rows_visible_to(session_maker, org_a, integration_id)
        assert rows, "sync reported success but no erp_entities rows are visible"

        # Real Dataverse shape, not something we invented.
        assert any("systemuserid" in (r.entity_data or {}) for r in rows), (
            "rows landed but do not look like Dataverse systemusers records"
        )
        assert all(str(r.organization_id) == org_a for r in rows)
        assert all(r.source_system == "dynamics" for r in rows)

    async def test_another_tenant_cannot_see_the_synced_rows(
        self, session_maker, seeded_orgs
    ):
        """THE ASSERTION THAT NEEDS A NON-OWNER ROLE TO MEAN ANYTHING.

        Real ERP data is the most sensitive thing this platform ingests — supplier
        names, order values, employee records. A leak here is a leak of another
        company's books.
        """
        from app.api.erp_integrations import run_erp_sync

        org_a = str(seeded_orgs["org_a_id"])
        org_b = str(seeded_orgs["org_b_id"])
        integration_id = await _make_integration(session_maker, org_a)

        await run_erp_sync(integration_id, org_a, [ENTITY_SET])

        assert await _rows_visible_to(session_maker, org_a, integration_id)
        leaked = await _rows_visible_to(session_maker, org_b, integration_id)
        assert leaked == [], (
            f"{len(leaked)} rows of another tenant's live ERP data are visible to org B"
        )

    async def test_rls_is_actually_being_enforced_in_this_test(self, session_maker):
        """Guards the guard. If the fixture role could bypass RLS — a superuser, an
        owner, or BYPASSRLS — every isolation assertion above would pass with the
        bug present. This fails loudly rather than letting them pass vacuously.
        """
        async with session_maker() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT current_user, "
                        "  (SELECT rolsuper FROM pg_roles WHERE rolname = current_user), "
                        "  (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"
                    )
                )
            ).first()
        user, is_super, bypasses = row
        assert not is_super, f"{user} is a superuser; RLS would not apply"
        assert not bypasses, f"{user} has BYPASSRLS; RLS would not apply"

        async with session_maker() as db:
            owner = (
                await db.execute(
                    text("SELECT tableowner FROM pg_tables WHERE tablename = 'erp_entities'")
                )
            ).scalar()
            current = (await db.execute(text("SELECT current_user"))).scalar()
        assert owner != current, (
            f"the test role owns erp_entities ({owner}); owners bypass RLS without FORCE"
        )

    async def test_sync_status_records_what_happened(self, session_maker, seeded_orgs):
        from app.api.erp_integrations import run_erp_sync

        org_a = str(seeded_orgs["org_a_id"])
        integration_id = await _make_integration(session_maker, org_a)
        await run_erp_sync(integration_id, org_a, [ENTITY_SET])

        async with session_maker() as db:
            await db.execute(
                text("SELECT set_config('app.current_org_id', :org, false)"),
                {"org": org_a},
            )
            status = (
                await db.execute(
                    select(ERPSyncStatus).where(
                        ERPSyncStatus.integration_id == integration_id
                    )
                )
            ).scalars().first()

        assert status is not None, "no erp_sync_status row was written"
        assert status.last_sync_status == "success"
        assert status.records_synced > 0
        assert str(status.organization_id) == org_a

    async def test_a_second_sync_updates_rather_than_duplicates(
        self, session_maker, seeded_orgs
    ):
        """Syncs are polled and repeat. Re-running must upsert, not accumulate — a
        duplicating sync inflates every count built on erp_entities."""
        from app.api.erp_integrations import run_erp_sync

        org_a = str(seeded_orgs["org_a_id"])
        integration_id = await _make_integration(session_maker, org_a)

        await run_erp_sync(integration_id, org_a, [ENTITY_SET])
        first = await _rows_visible_to(session_maker, org_a, integration_id)

        await run_erp_sync(integration_id, org_a, [ENTITY_SET])
        second = await _rows_visible_to(session_maker, org_a, integration_id)

        assert len(second) == len(first), (
            f"a repeat sync grew erp_entities from {len(first)} to {len(second)} rows"
        )
        ids = [r.entity_id for r in second]
        assert len(ids) == len(set(ids)), "duplicate entity_id rows after re-sync"


class TestCorrelationReportingOnTheLivePath:
    async def test_dynamics_correlation_is_reported_as_unrouted_not_silent(
        self, session_maker, seeded_orgs
    ):
        """Dynamics has no correlation transformer yet. The sync must SAY so.

        The alternative — reusing the SAP transformer because it is importable —
        would map none of Dataverse's field names, find no anomalies, and report a
        clean run over data it never actually understood.
        """
        from app.api.erp_integrations import run_erp_sync

        org_a = str(seeded_orgs["org_a_id"])
        integration_id = await _make_integration(session_maker, org_a)

        summary = await run_erp_sync(integration_id, org_a, [ENTITY_SET])
        correlation = summary[ENTITY_SET].get("correlation")

        assert correlation is not None, "the sync reported no correlation outcome at all"
        assert correlation["routed"] is False
        assert correlation["analyzed"] == 0
        assert correlation["reason"], "unrouted, but with no reason given"
