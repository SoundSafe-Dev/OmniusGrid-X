"""`run_erp_sync` writes to FORCEd tables from a background task. Nothing ran that path.

Migration 058 adds `FORCE ROW LEVEL SECURITY` to the five ERP tables that have carried a policy
since 020/033 and never had FORCE. Without FORCE the table OWNER bypasses the policy, and the
application connects as the owner in several deployments — so `relrowsecurity = true` reads as
protected while the only connection that matters is exempt. `app/api/erp_integrations.py` records
what that cost in a comment: its background sync *"appeared to work only because no ERP table has
FORCE ROW LEVEL SECURITY and the dev connection owns them."*

The policy-coverage baseline made each of the five entries name its own precondition, and
`erp_sync_status`'s said: *"that function already calls _set_tenant_guc, so FORCE may be safe here
— it needs one real-DB run to confirm before the migration."*

**There was no such run available.** The two real-Postgres suites that exercise the sync path —
`test_erp_sync_e2e_realdb.py` and `test_erp_platform_integration_realdb.py` — skip in full
without live Dataverse credentials: 29 of 54 tests, and every one that touches `run_erp_sync`.
Running them and reading "25 passed" would have confirmed the migration against a suite that
never executed the code the migration can break. That is the failure this file exists to avoid,
and it is why the connector is stubbed here: the vendor call is the only part that needs
credentials, and it is not the part under test.

WHAT IS UNDER TEST is the tenant binding of a background writer. `run_erp_sync` opens its own
session (there is no request behind it), sets `app.current_org_id` explicitly, and holds ONE
transaction with a single commit at the end — so the transaction-scoped GUC covers every
statement. Under FORCE, if any of that is wrong, the inserts are rejected instead of silently
succeeding as the owner.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio

ENTITY_TYPE = "customers"


class _StubConnector:
    """Returns fixed records instead of calling a vendor. The vendor call is the only part of
    this path that needs credentials, and it is not what FORCE can break."""

    def __init__(self, records):
        self._records = records
        self.closed = False

    async def fetch_data(self, entity_type):
        return list(self._records)

    async def close(self):
        self.closed = True


@pytest.fixture
def stub_connector(monkeypatch):
    from app.api import erp_integrations as module

    stub = _StubConnector(
        [
            {"id": "cust-1", "name": "Acme"},
            {"id": "cust-2", "name": "Globex"},
        ]
    )

    class _Factory:
        @staticmethod
        def create(_integration):
            return stub

    monkeypatch.setattr(module, "ERPConnectorFactory", _Factory)
    return stub


def _seed_integration(admin_sync_url: str, organization_id) -> str:
    """An ERP integration owned by `organization_id`, inserted as superuser (the seed itself
    must not be subject to the policy it is setting up a test for)."""
    import json

    import psycopg2

    integration_id = str(uuid.uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO integration_configurations "
                "(id, integration_type, integration_name, organization_id, configuration, "
                " is_active, erp_type) "
                "VALUES (%s, 'erp', 'Stub ERP', %s, %s, true, 'sap')",
                (integration_id, str(organization_id), json.dumps({"erp_type": "sap"})),
            )
    finally:
        conn.close()
    return integration_id


def _rows(admin_sync_url: str, table: str, integration_id: str):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT organization_id FROM {table} WHERE integration_id = %s",
                (integration_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


class TestTheTablesAreActuallyForced:
    """Non-vacuity for everything below: if FORCE is not on, the sync writing successfully
    proves nothing — the owner would bypass the policy exactly as it always did."""

    @pytest.mark.parametrize(
        "table",
        [
            "erp_entities",
            "erp_sync_status",
            "erp_data_mappings",
            "erp_correlations",
            "erp_integration_events",
        ],
    )
    async def test_force_is_on(self, app, admin_sync_url, table):
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                    (table,),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        assert row is not None, f"{table} is missing from the schema"
        enabled, forced = row
        assert enabled, f"{table} has no row-level security at all"
        assert forced, (
            f"{table} has RLS enabled but not FORCEd — the owner bypasses the policy, which is "
            "the state migration 058 exists to end, and it reads as protected either way"
        )


class TestTheBackgroundSyncWritesUnderThePolicy:
    async def test_a_sync_lands_its_rows(
        self, app, admin_sync_url, seeded_orgs, stub_connector
    ):
        """THE ASSERTION THIS FILE EXISTS FOR. Under FORCE, an unbound insert is REJECTED — so
        this passing is evidence that `_set_tenant_guc` reaches every statement in the function,
        not just the first."""
        from app.api.erp_integrations import run_erp_sync

        org_a = str(seeded_orgs["org_a_id"])
        integration_id = _seed_integration(admin_sync_url, org_a)

        summary = await run_erp_sync(integration_id, org_a, [ENTITY_TYPE])

        assert "error" not in summary, summary
        assert summary[ENTITY_TYPE]["status"] == "success", summary
        assert summary[ENTITY_TYPE]["records_synced"] == 2, summary

        entities = _rows(admin_sync_url, "erp_entities", integration_id)
        assert len(entities) == 2, (
            f"the sync reported success and wrote {len(entities)} entities — the shape the "
            "erp_integrations comment describes, where the write is rejected and the summary "
            "says success anyway"
        )
        assert {str(r[0]) for r in entities} == {org_a}

        status_rows = _rows(admin_sync_url, "erp_sync_status", integration_id)
        assert len(status_rows) == 1
        assert str(status_rows[0][0]) == org_a

    async def test_a_second_sync_updates_rather_than_duplicating(
        self, app, admin_sync_url, seeded_orgs, stub_connector
    ):
        """The second run takes the UPDATE branch for both tables — a different statement, and
        under FORCE an update whose row the policy hides matches nothing and silently succeeds.
        The row count is what distinguishes that from working."""
        from app.api.erp_integrations import run_erp_sync

        org_a = str(seeded_orgs["org_a_id"])
        integration_id = _seed_integration(admin_sync_url, org_a)

        await run_erp_sync(integration_id, org_a, [ENTITY_TYPE])
        summary = await run_erp_sync(integration_id, org_a, [ENTITY_TYPE])

        assert summary[ENTITY_TYPE]["records_synced"] == 2, summary
        assert len(_rows(admin_sync_url, "erp_entities", integration_id)) == 2
        assert len(_rows(admin_sync_url, "erp_sync_status", integration_id)) == 1

    async def test_the_other_tenant_cannot_read_the_synced_rows(
        self, app, client_a, client_b, admin_sync_url, seeded_orgs, stub_connector
    ):
        """The point of the policy, exercised through the HTTP surface rather than asserted of
        the DDL — and BOTH directions, because "B sees nothing" passes just as well when the
        endpoint is broken for everyone.

        The 404 is the second finding here. Org B originally got `200 []`, which leaks nothing
        — the filter and the policy both held — but `[]` also meant "this integration has never
        synced", and that ambiguity was there for the OWNER too. The integration is now resolved
        first, so an empty list has exactly one meaning.
        """
        from app.api.erp_integrations import run_erp_sync

        org_a = str(seeded_orgs["org_a_id"])
        integration_id = _seed_integration(admin_sync_url, org_a)
        await run_erp_sync(integration_id, org_a, [ENTITY_TYPE])

        mine = await client_a.get(f"/api/v1/erp/integrations/{integration_id}/sync-status")
        assert mine.status_code == 200, mine.text
        assert [s["entity_type"] for s in mine.json()] == [ENTITY_TYPE], mine.json()

        theirs = await client_b.get(f"/api/v1/erp/integrations/{integration_id}/sync-status")
        assert theirs.status_code == 404, (
            f"org B got {theirs.status_code} for org A's integration: {theirs.text[:300]}"
        )

    async def test_an_integration_that_never_synced_is_not_the_same_as_a_missing_one(
        self, app, client_a, admin_sync_url, seeded_orgs
    ):
        """The other half of the disambiguation, and the one a tenant actually hits: their own
        integration, no sync yet, `200 []` — distinguishable from a wrong id's 404."""
        integration_id = _seed_integration(admin_sync_url, str(seeded_orgs["org_a_id"]))

        never = await client_a.get(f"/api/v1/erp/integrations/{integration_id}/sync-status")
        assert never.status_code == 200, never.text
        assert never.json() == []

        missing = await client_a.get(f"/api/v1/erp/integrations/{uuid.uuid4()}/sync-status")
        assert missing.status_code == 404
