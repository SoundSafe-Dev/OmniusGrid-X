"""Inbound ERP webhooks must authenticate, resolve the right tenant, and grant nothing else.

THE BREAKAGE. `POST /api/v1/erp/webhooks/{erp_type}` rejected **every** inbound webhook
with 404 "no active ERP integration". `integration_configurations` is FORCE ROW LEVEL
SECURITY keyed on `app.current_org_id`, and the receiver is an unauthenticated vendor
callback — there is no user, so no GUC is set when the candidate lookup runs. The policy
matched nothing, and the whole ERP webhook surface was dead.

WHY IT COULD NOT BE A DEPENDENCY SWAP. The route is one shared path per vendor with
nothing in the URL or headers naming the organisation. The tenant is *whoever holds the
secret that verifies these exact bytes* — the signature is the only trustworthy evidence
in the request. Resolving it therefore requires reading candidates from every
organisation, before any tenant is known. `get_tenant_db` cannot help: it derives the
tenant from an authenticated user that does not exist here.

THE FIX. Migration 052 adds a second, deliberately narrow policy —
`webhook_tenant_resolution` — permitting **SELECT only**, on **active ERP rows only**,
**only while `app.erp_webhook_lookup = 'on'`**. The handler sets that GUC
transaction-locally immediately before the candidate query and clears it in a `finally`,
so it is already off for the event INSERT and for every other path.

The narrowness IS the security argument, so this file tests it rather than asserting it:
that the flag cannot write, cannot see dormant or non-ERP integrations, and does not
leak into ordinary tenant sessions. A policy justified by a comment is not justified.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

SECRET_A = "org-a-webhook-secret-0001"
SECRET_B = "org-b-webhook-secret-0002"


def _signed(payload: dict, secret: str):
    body = json.dumps(payload).encode()
    return body, hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _event(event_id: str) -> dict:
    return {
        "event_type": "purchase_order.created",
        "event_id": event_id,
        "entity_type": "purchase_order",
    }


@pytest_asyncio.fixture
async def two_sap_integrations(admin_sync_url, seeded_orgs):
    """BOTH organisations running SAP, each with its own secret.

    This is the configuration the signature-selects-tenant design exists for, and the
    one a per-vendor shared path cannot otherwise disambiguate.
    """
    import psycopg2

    int_a, int_b = uuid.uuid4(), uuid.uuid4()
    dormant, non_erp = uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        for iid, org_key, secret, active, itype in (
            (int_a, "org_a_id", SECRET_A, True, "erp"),
            (int_b, "org_b_id", SECRET_B, True, "erp"),
            # A dormant ERP row and a non-ERP row, to prove the policy excludes them.
            (dormant, "org_b_id", "dormant-secret", False, "erp"),
            (non_erp, "org_b_id", "non-erp-secret", True, "crm"),
        ):
            cur.execute(
                "INSERT INTO integration_configurations "
                "(id, organization_id, integration_name, integration_type, erp_type, "
                " is_active, configuration) VALUES (%s, %s, %s, %s, 'sap', %s, %s)",
                (str(iid), str(seeded_orgs[org_key]), f"int-{iid.hex[:6]}", itype,
                 active, json.dumps({"webhook_secret": secret})),
            )
    yield {"a": int_a, "b": int_b, "dormant": dormant, "non_erp": non_erp}
    with conn.cursor() as cur:
        for iid in (int_a, int_b, dormant, non_erp):
            cur.execute(
                "DELETE FROM erp_integration_events WHERE integration_id = %s", (str(iid),)
            )
            cur.execute(
                "DELETE FROM integration_configurations WHERE id = %s", (str(iid),)
            )
    conn.close()


@pytest_asyncio.fixture
def post_webhook(app):
    from httpx import ASGITransport, AsyncClient

    async def _post(payload: dict, secret: str, erp_type: str = "sap"):
        body, signature = _signed(payload, secret)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                f"/api/v1/erp/webhooks/{erp_type}",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-webhook-signature": signature,
                },
            )

    return _post


class TestTheWebhookIsAcceptedAtAll:
    async def test_a_correctly_signed_webhook_succeeds(
        self, post_webhook, two_sap_integrations
    ):
        """THE ASSERTION THIS FILE EXISTS FOR. Every inbound webhook was 404."""
        response = await post_webhook(_event("evt-accept-1"), SECRET_A)
        assert response.status_code == 200, response.text

    async def test_the_event_is_actually_stored(
        self, post_webhook, two_sap_integrations, admin_sync_url
    ):
        """A 200 proves the signature verified, not that anything was written — the
        INSERT runs under a different GUC than the lookup."""
        import psycopg2

        await post_webhook(_event("evt-stored-1"), SECRET_A)
        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT integration_id FROM erp_integration_events WHERE event_id = %s",
                    ("evt-stored-1",),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        assert row is not None, "the webhook was accepted but no event was stored"
        assert str(row[0]) == str(two_sap_integrations["a"])


class TestTheSignatureSelectsTheTenant:
    """The design's central claim, and it is only testable with two tenants on the
    same vendor."""

    async def test_each_secret_resolves_to_its_own_integration(
        self, post_webhook, two_sap_integrations, admin_sync_url
    ):
        import psycopg2

        await post_webhook(_event("evt-a"), SECRET_A)
        await post_webhook(_event("evt-b"), SECRET_B)

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT event_id, integration_id FROM erp_integration_events "
                    "WHERE event_id IN ('evt-a', 'evt-b')"
                )
                filed = {eid: str(iid) for eid, iid in cur.fetchall()}
        finally:
            conn.close()

        assert filed.get("evt-a") == str(two_sap_integrations["a"])
        assert filed.get("evt-b") == str(two_sap_integrations["b"]), (
            "org B's webhook was filed against the wrong tenant's integration"
        )

    async def test_a_forged_signature_is_rejected(self, app, two_sap_integrations):
        from httpx import ASGITransport, AsyncClient

        body = json.dumps(_event("evt-forged")).encode()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/erp/webhooks/sap",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-webhook-signature": "deadbeef",
                },
            )
        assert response.status_code == 401, response.text

    async def test_an_unknown_vendor_is_not_authenticated(
        self, post_webhook, two_sap_integrations
    ):
        """`oracle` has no active integration, so there is nothing to resolve against."""
        response = await post_webhook(_event("evt-oracle"), SECRET_A, erp_type="oracle")
        assert response.status_code in (401, 404), response.text


class TestThePolicyGrantsNothingElse:
    """The narrowness of `webhook_tenant_resolution` is the whole security argument.
    These exercise the policy directly, with the flag set by hand."""

    @pytest_asyncio.fixture
    async def flagged(self, tenant_async_url):
        """A session with the lookup flag on and NO tenant GUC — exactly the state
        the receiver is in during the candidate query."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        engine = create_async_engine(tenant_async_url, future=True, poolclass=NullPool)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as session:
            await session.execute(
                text("SELECT set_config('app.erp_webhook_lookup', 'on', true)")
            )
            yield session
        await engine.dispose()

    async def test_the_flag_reveals_active_erp_rows(self, flagged, two_sap_integrations):
        """Guards the guard: if the flag revealed nothing, every assertion below would
        pass while proving nothing."""
        visible = {
            str(r[0])
            for r in (
                await flagged.execute(text("SELECT id FROM integration_configurations"))
            ).all()
        }
        assert str(two_sap_integrations["a"]) in visible
        assert str(two_sap_integrations["b"]) in visible

    async def test_the_flag_hides_dormant_integrations(self, flagged, two_sap_integrations):
        visible = {
            str(r[0])
            for r in (
                await flagged.execute(text("SELECT id FROM integration_configurations"))
            ).all()
        }
        assert str(two_sap_integrations["dormant"]) not in visible, (
            "a deactivated integration is readable through the webhook lookup policy"
        )

    async def test_the_flag_hides_non_erp_integrations(self, flagged, two_sap_integrations):
        visible = {
            str(r[0])
            for r in (
                await flagged.execute(text("SELECT id FROM integration_configurations"))
            ).all()
        }
        assert str(two_sap_integrations["non_erp"]) not in visible, (
            "a non-ERP integration is readable through the webhook lookup policy"
        )

    async def test_the_flag_does_not_permit_writing(
        self, flagged, two_sap_integrations, admin_sync_url
    ):
        """FOR SELECT only. If the flag ever permitted UPDATE, an unauthenticated
        callback path could rewrite another tenant's integration.

        NOTE THE SHAPE OF THE REFUSAL: RLS does not raise on a write it disallows, it
        filters the rows the statement can see, so the UPDATE simply affects zero rows.
        An earlier version of this test expected an exception and failed — the same
        "fails quiet" property that made every defect in this sweep hard to notice.
        """
        import psycopg2

        result = await flagged.execute(
            text(
                "UPDATE integration_configurations SET integration_name = 'hijacked' "
                "WHERE id = :i"
            ),
            {"i": str(two_sap_integrations["b"])},
        )
        assert result.rowcount == 0, (
            "the webhook lookup flag permitted an UPDATE — it is meant to be FOR SELECT"
        )
        await flagged.commit()

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT integration_name FROM integration_configurations WHERE id = %s",
                    (str(two_sap_integrations["b"]),),
                )
                assert cur.fetchone()[0] != "hijacked", "the row was actually rewritten"
        finally:
            conn.close()

    async def test_without_the_flag_nothing_is_visible(
        self, tenant_async_url, two_sap_integrations
    ):
        """The pre-fix state, pinned: no flag and no tenant GUC sees zero rows. If this
        ever returns rows, the base tenant policy has been weakened."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        engine = create_async_engine(tenant_async_url, future=True, poolclass=NullPool)
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as session:
            rows = (
                await session.execute(text("SELECT id FROM integration_configurations"))
            ).all()
        await engine.dispose()
        assert rows == [], "integration_configurations is readable with no tenant context"


class TestTheFlagDoesNotLeak:
    async def test_an_ordinary_tenant_session_still_sees_only_its_own(
        self, client_a, two_sap_integrations
    ):
        """The flag is transaction-local and cleared in a `finally`. If it leaked onto a
        pooled connection, the authenticated ERP list would show other tenants.

        BOTH DIRECTIONS (FS-431). This asserted only that org B's row was absent, and an
        EMPTY LIST satisfies that perfectly. Found by breaking `tenant_session`'s GUC bind
        globally and looking for tenancy tests that still passed: with every scoped read
        returning nothing, this one was still green.

        `test_the_flag_reveals_active_erp_rows` does assert positive visibility — but on
        the raw `flagged` session, not through the API. Nothing checked that an ordinary
        authenticated caller can see their own integration, which is the thing the endpoint
        exists to do.
        """
        response = await client_a.get("/api/v1/erp/integrations")
        assert response.status_code == 200, response.text
        payload = response.json()
        rows = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
        ids = {row.get("id") for row in rows}
        assert str(two_sap_integrations["a"]) in ids, (
            "org A cannot see its OWN integration through the authenticated list. Without "
            "this, the absence assertion below is satisfied by the list being empty — "
            "which is what a broken tenant binding produces"
        )
        assert str(two_sap_integrations["b"]) not in ids, (
            "another tenant's integration is visible through the authenticated list — "
            "the webhook lookup flag leaked"
        )

    async def test_a_webhook_then_a_tenant_read_is_still_scoped(
        self, post_webhook, client_a, two_sap_integrations
    ):
        """Order matters: run the webhook first so the flag has been set on some
        connection, then read as a tenant."""
        await post_webhook(_event("evt-leak-check"), SECRET_A)
        response = await client_a.get("/api/v1/erp/integrations")
        payload = response.json()
        rows = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
        assert str(two_sap_integrations["b"]) not in {row.get("id") for row in rows}
