"""Two tenants must not be able to share an inbound webhook secret.

WHY THIS MATTERS. The inbound webhook path carries only the erp_type:

    POST /api/v1/erp/webhooks/sap

Nothing in the URL or headers names the organisation, so the route resolves the tenant
by trying each active integration of that erp_type and accepting the one whose
`webhook_secret` verifies the request's exact bytes. The signature IS the evidence,
which is correct — and it depends entirely on the secret being unique. Two integrations
sharing one means both verify, and attribution becomes "whichever was tried first": one
tenant's purchase orders and supplier names filed against another tenant's records.

WHY THE DATABASE ENFORCES IT AND NOT THE APPLICATION. `integration_configurations` is
RLS-protected, so a create request running with `app.current_org_id` set to its own
organisation **cannot see another tenant's rows** to compare against — which is exactly
the property we want everywhere else. A unique index is enforced at the storage layer
regardless of RLS, so it constrains rows the inserting session may not read. That makes
it the only correct place for this rule, and it is why this test needs real Postgres:
on SQLite, or with `create_all` instead of the migration chain, there is no index and
the assertion would pass while proving nothing.

Migration: 049_webhook_secret_uniqueness.sql.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

ERP_BASE = "/api/v1/erp/integrations"

SHARED_SECRET = "a-secret-two-tenants-should-not-share"


def _payload(name: str, *, webhook_secret: str | None, erp_type: str = "sap") -> dict:
    return {
        "integration_name": name,
        "erp_type": erp_type,
        "auth_type": "oauth2",
        "base_url": "https://erp.example.com",
        "auth_config": {"client_id": "c", "client_secret": "s"},
        "webhook_secret": webhook_secret,
    }


@pytest.fixture
async def session_maker(app):
    from app.db import database as db_module

    return db_module.AsyncSessionLocal


class TestTheIndexExists:
    async def test_the_unique_index_is_present(self, session_maker):
        """Guards the guard. Without the index every assertion below passes while
        proving nothing — and the schema is built from the migration chain precisely so
        this cannot silently drift."""
        async with session_maker() as db:
            present = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM pg_indexes "
                        "WHERE indexname = 'uq_erp_integration_webhook_secret'"
                    )
                )
            ).scalar()
        assert present == 1, (
            "migration 049 did not create uq_erp_integration_webhook_secret; the "
            "uniqueness assertions in this file would pass vacuously"
        )


class TestCrossTenantCollision:
    async def test_a_second_tenant_cannot_claim_the_same_secret(self, client_a, client_b):
        """THE ASSERTION THIS FILE EXISTS FOR.

        Org B is not merely told "no" by application logic that happened to look — it
        genuinely cannot see org A's row. The constraint is what stops it.
        """
        first = await client_a.post(ERP_BASE, json=_payload("a-sap", webhook_secret=SHARED_SECRET))
        assert first.status_code in (200, 201), first.text

        second = await client_b.post(ERP_BASE, json=_payload("b-sap", webhook_secret=SHARED_SECRET))
        assert second.status_code == 409, (
            f"org B created an integration sharing org A's webhook secret "
            f"({second.status_code}); inbound webhooks would be attributed to "
            f"whichever row is tried first"
        )

    async def test_the_conflict_never_reveals_who_holds_it(self, client_a, client_b):
        """The collision is detected by an index precisely because the requesting
        session cannot read the other tenant's rows. The response must not undo that:
        confirming *which* tenant holds a secret is itself a disclosure.
        """
        await client_a.post(ERP_BASE, json=_payload("a-sap-2", webhook_secret=SHARED_SECRET + "-2"))
        second = await client_b.post(
            ERP_BASE, json=_payload("b-sap-2", webhook_secret=SHARED_SECRET + "-2")
        )
        assert second.status_code == 409

        body = second.text.lower()
        for leak in ("a-sap-2", "organization", "org_a", "tenant_a"):
            assert leak not in body, f"the 409 response leaks {leak!r}: {second.text}"
        # It must still be actionable rather than a bare code.
        assert "already in use" in body
        assert "distinct" in body

    async def test_distinct_secrets_are_accepted_for_both_tenants(self, client_a, client_b):
        """The constraint must not block the normal case. A rule that also rejects
        correct configuration gets disabled."""
        a = await client_a.post(ERP_BASE, json=_payload("a-ok", webhook_secret="secret-for-org-a"))
        b = await client_b.post(ERP_BASE, json=_payload("b-ok", webhook_secret="secret-for-org-b"))
        assert a.status_code in (200, 201), a.text
        assert b.status_code in (200, 201), b.text


class TestSameTenantAndNoSecret:
    async def test_one_tenant_cannot_reuse_its_own_secret_either(self, client_a):
        """Two integrations in the SAME organisation sharing a secret is equally
        ambiguous — the route tries candidates by erp_type, not by tenant."""
        first = await client_a.post(
            ERP_BASE, json=_payload("a-one", webhook_secret="same-org-duplicate")
        )
        assert first.status_code in (200, 201), first.text
        second = await client_a.post(
            ERP_BASE, json=_payload("a-two", webhook_secret="same-org-duplicate")
        )
        assert second.status_code == 409, second.text

    async def test_several_integrations_without_a_secret_are_fine(self, client_a):
        """Polling-only integrations are legitimate and must not collide with each
        other on NULL — which is why the index is partial."""
        for name in ("poll-1", "poll-2", "poll-3"):
            response = await client_a.post(ERP_BASE, json=_payload(name, webhook_secret=None))
            assert response.status_code in (200, 201), response.text

    async def test_an_empty_string_secret_is_treated_as_absent(self, client_a):
        """An empty secret is not a secret. It must not occupy the unique slot and
        block the next integration, and it must not authenticate anything either —
        `authenticate_webhook` rejects a falsy secret."""
        for name in ("empty-1", "empty-2"):
            response = await client_a.post(ERP_BASE, json=_payload(name, webhook_secret=""))
            assert response.status_code in (200, 201), response.text


class TestUpdatePathIsGuardedToo:
    async def test_updating_onto_another_tenants_secret_is_rejected(self, client_a, client_b):
        """The create path is the obvious one; an update that walks into a collision is
        the one that gets forgotten."""
        taken = "secret-held-by-org-a-already"
        created_a = await client_a.post(ERP_BASE, json=_payload("a-held", webhook_secret=taken))
        assert created_a.status_code in (200, 201), created_a.text

        created_b = await client_b.post(
            ERP_BASE, json=_payload("b-will-try", webhook_secret="b-own-secret")
        )
        assert created_b.status_code in (200, 201), created_b.text
        b_id = created_b.json()["id"]

        conflict = await client_b.put(f"{ERP_BASE}/{b_id}", json={"webhook_secret": taken})
        assert conflict.status_code == 409, (
            f"org B updated its integration onto org A's webhook secret "
            f"({conflict.status_code})"
        )

    async def test_an_unrelated_update_still_works(self, client_a):
        """The guard must only fire on a real collision."""
        created = await client_a.post(
            ERP_BASE, json=_payload("a-rename", webhook_secret="a-rename-secret")
        )
        assert created.status_code in (200, 201), created.text
        integration_id = created.json()["id"]

        updated = await client_a.put(
            f"{ERP_BASE}/{integration_id}", json={"integration_name": "a-renamed"}
        )
        assert updated.status_code == 200, updated.text


class TestConfigurationUpdatesActuallyPersist:
    """The PUT handler silently discarded every configuration change.

    It read `integration.configuration`, mutated that dict IN PLACE, and assigned the
    same object back. SQLAlchemy detects JSON-column changes by identity, so
    re-assigning the identical object left the attribute clean and **no UPDATE was
    emitted for that column** — while the endpoint returned 200 and logged
    `erp_integration_updated`.

    So `auth_config`, `rate_limit`, `timeout`, `webhook_secret` and `ip_whitelist` were
    all unsavable through the API. An operator rotating a webhook secret or correcting
    ERP credentials saw success and got nothing.

    Found incidentally — a collision test expected 409 and got 200 because the write
    never happened. These assert it directly, by reading the row back.
    """

    async def _configuration_of(self, session_maker, organization_id: str, integration_id: str) -> dict:
        """Read the row straight from the database.

        The GUC must be set: `integration_configurations` is RLS-protected, so a
        session without tenant context sees NOTHING and this helper would return `{}`
        for every integration -- making the assertions below fail for a reason that
        has nothing to do with the code under test. (It did, on the first run.)
        """
        from sqlalchemy import select

        from app.db.models import IntegrationConfiguration

        async with session_maker() as db:
            await db.execute(
                text("SELECT set_config('app.current_org_id', :org, false)"),
                {"org": str(organization_id)},
            )
            row = (
                await db.execute(
                    select(IntegrationConfiguration).where(
                        IntegrationConfiguration.id == integration_id
                    )
                )
            ).scalar_one_or_none()
            configuration = dict(row.configuration or {}) if row else {}
            # Never leave tenant context on a pooled connection.
            await db.execute(text("SELECT set_config('app.current_org_id', '', false)"))
            await db.commit()
            return configuration

    async def test_a_rotated_webhook_secret_is_actually_stored(
        self, client_a, session_maker, seeded_orgs
    ):
        created = await client_a.post(
            ERP_BASE, json=_payload("rotate-me", webhook_secret="original-secret-value")
        )
        assert created.status_code in (200, 201), created.text
        integration_id = created.json()["id"]

        updated = await client_a.put(
            f"{ERP_BASE}/{integration_id}", json={"webhook_secret": "rotated-secret-value"}
        )
        assert updated.status_code == 200, updated.text

        stored = await self._configuration_of(session_maker, str(seeded_orgs["org_a_id"]), integration_id)
        assert stored.get("webhook_secret") == "rotated-secret-value", (
            "the PUT reported success but the webhook secret on disk is still "
            f"{stored.get('webhook_secret')!r} — rotation is impossible via the API"
        )

    async def test_corrected_credentials_are_actually_stored(
        self, client_a, session_maker, seeded_orgs
    ):
        """The most damaging case: an operator fixing a wrong client secret."""
        created = await client_a.post(
            ERP_BASE, json=_payload("fix-creds", webhook_secret="fix-creds-secret")
        )
        integration_id = created.json()["id"]

        await client_a.put(
            f"{ERP_BASE}/{integration_id}",
            json={"auth_config": {"client_id": "corrected", "client_secret": "corrected"}},
        )

        stored = await self._configuration_of(session_maker, str(seeded_orgs["org_a_id"]), integration_id)
        assert stored["auth_config"]["client_id"] == "corrected", (
            "credentials corrected through the API were silently discarded"
        )

    async def test_other_configuration_fields_persist_too(self, client_a, session_maker, seeded_orgs):
        created = await client_a.post(
            ERP_BASE, json=_payload("persist-all", webhook_secret="persist-all-secret")
        )
        integration_id = created.json()["id"]

        await client_a.put(
            f"{ERP_BASE}/{integration_id}",
            json={"timeout": 99, "ip_whitelist": ["203.0.113.7"]},
        )

        stored = await self._configuration_of(session_maker, str(seeded_orgs["org_a_id"]), integration_id)
        assert stored.get("timeout") == 99
        assert stored.get("ip_whitelist") == ["203.0.113.7"]

    async def test_an_update_does_not_wipe_untouched_keys(self, client_a, session_maker, seeded_orgs):
        """The copy must preserve what the request did not mention. A fix that made
        writes land but dropped everything else would be worse than the bug."""
        created = await client_a.post(
            ERP_BASE, json=_payload("keep-rest", webhook_secret="keep-rest-secret")
        )
        integration_id = created.json()["id"]

        await client_a.put(f"{ERP_BASE}/{integration_id}", json={"timeout": 45})

        stored = await self._configuration_of(session_maker, str(seeded_orgs["org_a_id"]), integration_id)
        assert stored.get("timeout") == 45
        assert stored.get("webhook_secret") == "keep-rest-secret", "an unrelated update wiped the secret"
        assert stored.get("base_url") == "https://erp.example.com", "an unrelated update wiped base_url"
