"""The demo seeder's ERP integration must be able to receive a signed webhook.

Task-pool item 31. The seeder set `"webhook_secret": "demo-secret"` — a fixed literal, which is
two problems in one string.

**Migration 049 puts a UNIQUE index on `configuration->>'webhook_secret'`**, because the
receiver identifies an integration BY its secret: it verifies the request's exact bytes against
each candidate, so two integrations sharing a secret makes the sender ambiguous. One seeded
integration never collides. A second one — or a second demo organisation — is rejected by the
index with a constraint error rather than anything a reader could act on.

**And a signing key committed to the repository is not a secret.** A demo deployment would
accept a forged webhook from anybody who has cloned this.

The seeder derives one per integration id now: distinct between integrations, and stable across
re-seeds, because the seeder deletes and reinserts on every run and an operator wiring up a real
sender needs the value to survive that.

WHAT THIS FILE PINS, and it is the half the pool item asked for that a unit test cannot give:
that a webhook signed with the seeded secret is actually ACCEPTED end to end. The seeder writing
a well-formed secret proves nothing if the receiver would reject it anyway.
"""

from __future__ import annotations

import json
import uuid

import pytest

pytestmark = pytest.mark.asyncio


def _seeded_secret(integration_id: str) -> str:
    """The seeder's own derivation, imported rather than recomputed.

    Copying the formula here would let the two drift and the test would still pass — the
    fixture-encodes-the-same-assumption trap that `compute_signature`'s docstring records
    about the old signature tests.
    """
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "seed_demo_data.py"
    spec = importlib.util.spec_from_file_location("_seed_demo_data", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:  # the script guards its own CLI entry point
        pass
    return module._webhook_secret(integration_id)


def _seed_integration(admin_sync_url: str, org_id: str, integration_id: str, secret: str):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO integration_configurations "
                "(id, integration_type, integration_name, organization_id, configuration, "
                " is_active, erp_type) "
                "VALUES (%s, 'erp', 'Demo SAP', %s, %s, true, 'sap')",
                (integration_id, org_id,
                 json.dumps({"erp_type": "sap", "webhook_secret": secret})),
            )
    finally:
        conn.close()


class TestTheSeededSecretIsUsable:
    async def test_a_webhook_signed_with_it_is_accepted(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """THE ASSERTION THIS FILE EXISTS FOR."""
        from app.api.erp_webhooks import compute_signature

        integration_id = str(uuid.uuid4())
        secret = _seeded_secret(integration_id)
        _seed_integration(admin_sync_url, str(seeded_orgs["org_a_id"]), integration_id, secret)

        # `event_id` is required as well as `event_type` — the receiver needs both to
        # deduplicate a replay. The first version of this test sent neither and got a 400,
        # which was already proof the SIGNATURE had been accepted: an unsigned or wrongly
        # signed request never reaches the payload check at all.
        body = {
            "event_type": "purchase_order.updated",
            "event_id": "evt-1001",
            "entity_type": "purchase_order",
            "id": "PO-1001",
        }
        raw = json.dumps(body).encode()

        resp = await client_a.post(
            "/api/v1/erp/webhooks/sap",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": compute_signature(secret, raw),
                "X-Event-Type": "purchase_order.updated",
            },
        )

        assert resp.status_code < 400, resp.text

    async def test_a_wrong_signature_is_rejected(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """The control. An endpoint that accepted everything would pass the test above, and
        this whole item is about a signing key being meaningful."""
        integration_id = str(uuid.uuid4())
        secret = _seeded_secret(integration_id)
        _seed_integration(admin_sync_url, str(seeded_orgs["org_a_id"]), integration_id, secret)

        raw = json.dumps({
            "event_type": "purchase_order.updated",
            "event_id": "evt-1002",
            "entity_type": "purchase_order",
        }).encode()

        resp = await client_a.post(
            "/api/v1/erp/webhooks/sap",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": "0" * 64,
                "X-Event-Type": "purchase_order.updated",
            },
        )

        assert resp.status_code == 401, resp.text


class TestTheSecretIsFitForTheUniqueIndex:
    def test_two_integrations_get_different_secrets(self):
        """Migration 049's unique index is the reason this matters: the receiver identifies an
        integration by its secret, so a shared one makes the sender ambiguous — and the second
        insert fails on a constraint rather than saying anything useful."""
        a = _seeded_secret("44444444-0000-4000-8000-000000000001")
        b = _seeded_secret("44444444-0000-4000-8000-000000000002")
        assert a != b

    def test_the_same_integration_gets_the_same_secret_across_runs(self):
        """The seeder deletes and reinserts on every run. A random secret would silently
        invalidate whatever a demo operator had configured on the sending side."""
        first = _seeded_secret("44444444-0000-4000-8000-000000000001")
        second = _seeded_secret("44444444-0000-4000-8000-000000000001")
        assert first == second

    def test_it_is_not_the_literal_that_was_committed(self):
        assert _seeded_secret("44444444-0000-4000-8000-000000000001") != "demo-secret"

    def test_the_literal_is_gone_from_the_seeder(self):
        """Comments stripped — rule 37. The note explaining the change quotes the old value."""
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1] / "scripts" / "seed_demo_data.py"
        ).read_text()
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        assert '"webhook_secret": "demo-secret"' not in code
