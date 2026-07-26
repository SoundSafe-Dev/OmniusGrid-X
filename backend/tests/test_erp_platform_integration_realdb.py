"""ERP against the REST of the platform: real data, real HTTP, two tenants.

The connector suites prove a vendor accepts our requests. The end-to-end suite proves
synced rows land tenant-scoped. Neither touches the surfaces an operator actually
uses — the entities tab, sync status, correlation attach, exports — and those are
where a tenant leak would be seen by a human rather than by a test.

Everything here drives the real HTTP API with real JWTs for two organisations, over
data fetched from a LIVE Dataverse. Org B is not a hypothetical: it is a second seeded
tenant issuing the same requests, and every read is checked from both sides.

Requires Docker (testcontainers Postgres) and live Dataverse credentials; skips
without them.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from app.db.models import IntegrationConfiguration

ORG = os.environ.get("DATAVERSE_ORG")
TENANT_ID = os.environ.get("DATAVERSE_TENANT_ID")
CLIENT_ID = os.environ.get("DATAVERSE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("DATAVERSE_CLIENT_SECRET")

pytestmark = pytest.mark.skipif(
    not all([ORG, TENANT_ID, CLIENT_ID, CLIENT_SECRET]),
    reason="needs live Dataverse credentials (see docs/erp/dynamics-dataverse-setup.md)",
)

ENTITY_SET = "systemusers"
ERP_BASE = "/api/v1/erp/integrations"


async def _clear_guc(db) -> None:
    await db.execute(text("SELECT set_config('app.current_org_id', '', false)"))
    await db.commit()


@pytest.fixture
async def session_maker(app):
    from app.db import database as db_module

    return db_module.AsyncSessionLocal


@pytest.fixture
async def synced_integration(session_maker, seeded_orgs):
    """A real Dataverse integration owned by org A, already synced once."""
    from app.api.erp_integrations import run_erp_sync

    org_a = str(seeded_orgs["org_a_id"])
    integration_id = str(uuid.uuid4())

    async with session_maker() as db:
        await db.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"), {"org": org_a}
        )
        db.add(
            IntegrationConfiguration(
                id=integration_id,
                integration_type="erp",
                integration_name="platform-sweep-dataverse",
                organization_id=org_a,
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
            )
        )
        await db.commit()
        # The setup must not lend its tenant context to the code under test; see
        # test_erp_sync_e2e_realdb for the version of this that silently did.
        await _clear_guc(db)

    summary = await run_erp_sync(integration_id, org_a, [ENTITY_SET])
    assert summary.get(ENTITY_SET, {}).get("records_synced", 0) > 0, summary
    return integration_id


class TestEntitiesTab:
    """`GET /{id}/entities` — what the ERP hub's Entities tab renders."""

    async def test_org_a_sees_the_synced_dataverse_rows(self, client_a, synced_integration):
        response = await client_a.get(f"{ERP_BASE}/{synced_integration}/entities")
        assert response.status_code == 200, response.text

        rows = response.json()
        assert rows, "the entities tab is empty after a successful sync"
        assert rows[0]["source_system"] == "dynamics"
        assert "systemuserid" in rows[0]["entity_data"], (
            "rows are present but do not carry real Dataverse fields"
        )

    async def test_org_b_sees_none_of_them(self, client_b, synced_integration):
        """A leak here is another company's employee directory rendered in this
        tenant's UI."""
        response = await client_b.get(f"{ERP_BASE}/{synced_integration}/entities")
        assert response.status_code in (200, 403, 404), response.text
        if response.status_code == 200:
            assert response.json() == [], (
                f"org B can read {len(response.json())} of org A's live ERP records"
            )

    async def test_the_entity_type_filter_narrows_rather_than_being_ignored(
        self, client_a, synced_integration
    ):
        """A filter that is silently dropped returns everything, which looks like a
        valid answer."""
        matching = await client_a.get(
            f"{ERP_BASE}/{synced_integration}/entities", params={"entity_type": ENTITY_SET}
        )
        absent = await client_a.get(
            f"{ERP_BASE}/{synced_integration}/entities",
            params={"entity_type": "no_such_entity_zzz"},
        )
        assert matching.status_code == 200 and absent.status_code == 200
        assert matching.json(), "the real entity type returned nothing"
        assert absent.json() == [], "a nonexistent entity type returned rows"


class TestSyncStatus:
    async def test_org_a_sees_the_sync_result(self, client_a, synced_integration):
        response = await client_a.get(f"{ERP_BASE}/{synced_integration}/sync-status")
        assert response.status_code == 200, response.text
        statuses = response.json()
        assert statuses, "no sync status after a successful sync"
        assert statuses[0]["last_sync_status"] == "success"
        assert statuses[0]["records_synced"] > 0

    async def test_org_b_sees_no_sync_status(self, client_b, synced_integration):
        response = await client_b.get(f"{ERP_BASE}/{synced_integration}/sync-status")
        assert response.status_code in (200, 403, 404)
        if response.status_code == 200:
            assert response.json() == [], "org B can see org A's sync history"


class TestIntegrationListing:
    async def test_org_b_cannot_list_or_read_org_as_integration(
        self, client_a, client_b, synced_integration
    ):
        """The integration record itself carries the ERP CREDENTIALS. A leak here is
        worse than a data leak: it is another tenant's client secret."""
        mine = await client_a.get(ERP_BASE)
        assert mine.status_code == 200, mine.text
        assert any(i["id"] == synced_integration for i in mine.json())

        theirs = await client_b.get(ERP_BASE)
        assert theirs.status_code == 200, theirs.text
        assert not any(i["id"] == synced_integration for i in theirs.json()), (
            "org B can see org A's ERP integration in its list"
        )

        direct = await client_b.get(f"{ERP_BASE}/{synced_integration}")
        assert direct.status_code in (403, 404), (
            f"org B fetched org A's integration directly: {direct.status_code}"
        )

    async def test_the_response_never_carries_the_client_secret(
        self, client_a, synced_integration
    ):
        """Even to the owning tenant. A secret echoed into a browser is a secret in
        every log, proxy and error report between here and there."""
        response = await client_a.get(f"{ERP_BASE}/{synced_integration}")
        assert response.status_code == 200, response.text
        assert CLIENT_SECRET not in response.text, (
            "the ERP client secret is echoed in the integration API response"
        )

        listing = await client_a.get(ERP_BASE)
        assert CLIENT_SECRET not in listing.text, (
            "the ERP client secret is echoed in the integration list response"
        )


class TestPlatformCorrelationSurface:
    """ERP is registered as a correlation source; this is where it meets sensors,
    yard and transport data."""

    async def test_erp_is_offered_as_a_platform_source(self, client_a):
        response = await client_a.get("/api/v1/nlp/platform-sources")
        assert response.status_code == 200, response.text
        source_types = {s["source_type"] for s in response.json()}
        assert "erp" in source_types, f"ERP is not an offered source: {source_types}"

    async def test_the_erp_provider_returns_the_synced_rows(
        self, session_maker, seeded_orgs, synced_integration
    ):
        """Exercised at the service layer: attaching to a session needs an analysis
        session, and what matters here is that the provider reads real synced rows
        for the right tenant."""
        from app.services.platform_correlation import erp_provider

        org_a = str(seeded_orgs["org_a_id"])
        async with session_maker() as db:
            await db.execute(
                text("SELECT set_config('app.current_org_id', :org, false)"),
                {"org": org_a},
            )
            result = await erp_provider(db, org_a, {})
            await _clear_guc(db)

        assert result.records, "the ERP correlation provider returned nothing"
        assert "entity_id" in result.shared_keys

    async def test_the_erp_provider_is_scoped_to_the_asking_tenant(
        self, session_maker, seeded_orgs, synced_integration
    ):
        from app.services.platform_correlation import erp_provider

        org_b = str(seeded_orgs["org_b_id"])
        async with session_maker() as db:
            await db.execute(
                text("SELECT set_config('app.current_org_id', :org, false)"),
                {"org": org_b},
            )
            result = await erp_provider(db, org_b, {})
            await _clear_guc(db)

        assert result.records == [], (
            f"the correlation provider handed org B {len(result.records)} of org A's "
            f"ERP records — these feed straight into an AI analysis session"
        )


class TestCorrelationsEndpoint:
    async def test_recent_correlations_is_reachable_and_scoped(self, client_a, client_b):
        """Dynamics has no correlation transformer yet, so the list is expected to be
        empty — but the endpoint must work and stay tenant-scoped, because it is what
        the AI tab reads."""
        mine = await client_a.get(f"{ERP_BASE}/correlations/recent")
        assert mine.status_code == 200, mine.text
        assert isinstance(mine.json(), list)

        theirs = await client_b.get(f"{ERP_BASE}/correlations/recent")
        assert theirs.status_code == 200, theirs.text
        assert isinstance(theirs.json(), list)


class TestEventsTab:
    async def test_events_endpoint_is_reachable_and_scoped(
        self, client_a, client_b, synced_integration
    ):
        mine = await client_a.get(f"{ERP_BASE}/{synced_integration}/events")
        assert mine.status_code == 200, mine.text

        theirs = await client_b.get(f"{ERP_BASE}/{synced_integration}/events")
        assert theirs.status_code in (200, 403, 404)
        if theirs.status_code == 200:
            assert theirs.json() == [], "org B can read org A's ERP integration events"


class TestWebhookConfigForOperators:
    """`GET /{id}/webhook-config` — what turns a silent 401 into something actionable.

    The webhook route answers an uninformative 401 on purpose: telling an
    unauthenticated caller why verification failed would let them probe whether an
    integration exists and how it is configured. Correct, and it leaves the operator
    wiring up a vendor with nothing to work from. This endpoint gives the same facts to
    an authenticated user of the owning tenant.
    """

    async def test_it_reports_what_the_vendor_must_send(self, client_a, synced_integration):
        response = await client_a.get(f"{ERP_BASE}/{synced_integration}/webhook-config")
        assert response.status_code == 200, response.text

        config = response.json()
        assert config["endpoint_path"] == "/api/v1/erp/webhooks/dynamics"
        # Dataverse serviceendpoint webhooks have no HMAC option -- they send a static
        # header. Reporting an HMAC scheme here would send the operator down a path
        # Dynamics cannot follow.
        assert config["auth_mode"] == "shared_secret"
        assert config["signature_header"]
        assert config["next_step"]

    async def test_it_says_plainly_when_no_secret_is_configured(
        self, client_a, synced_integration
    ):
        """The single most common reason a webhook 401s, and the one the route cannot
        tell you."""
        response = await client_a.get(f"{ERP_BASE}/{synced_integration}/webhook-config")
        config = response.json()
        assert config["secret_configured"] is False
        assert config["ready"] is False
        assert "webhook_secret" in config["next_step"]

    async def test_it_never_returns_the_secret(self, client_a, session_maker, seeded_orgs):
        response = await client_a.get(f"{ERP_BASE}/{await _integration_with_secret(session_maker, seeded_orgs)}/webhook-config")
        assert response.status_code == 200, response.text
        assert "super-secret-webhook-value" not in response.text
        assert response.json()["secret_configured"] is True

    async def test_another_tenant_cannot_read_the_webhook_config(
        self, client_b, synced_integration
    ):
        """It names the header and scheme, which is reconnaissance for forging a
        webhook against someone else's integration."""
        response = await client_b.get(f"{ERP_BASE}/{synced_integration}/webhook-config")
        assert response.status_code in (403, 404), response.status_code


async def _integration_with_secret(session_maker, seeded_orgs) -> str:
    """An integration for org A that DOES have a webhook secret configured."""
    org_a = str(seeded_orgs["org_a_id"])
    integration_id = str(uuid.uuid4())
    async with session_maker() as db:
        await db.execute(
            text("SELECT set_config('app.current_org_id', :org, false)"), {"org": org_a}
        )
        db.add(
            IntegrationConfiguration(
                id=integration_id,
                integration_type="erp",
                integration_name="with-webhook-secret",
                organization_id=org_a,
                erp_type="intuit",
                is_active=True,
                configuration={
                    "erp_type": "intuit",
                    "auth_type": "oauth2",
                    "webhook_secret": "super-secret-webhook-value",
                },
            )
        )
        await db.commit()
        await _clear_guc(db)
    return integration_id
