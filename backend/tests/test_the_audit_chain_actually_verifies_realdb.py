"""The audit hash chain verifies, and notices tampering (FS-743).

THE DEFECT THIS FILE WOULD HAVE CAUGHT ON DAY ONE. `audit_logs` has carried a hash chain
since migration 009 and `GET /api/v1/audit/verify` has existed just as long. They could
never agree:

    trigger   calculate_audit_hash(prev, to_jsonb(NEW))          -- the WHOLE row,
                                                                 -- including hash_chain
    endpoint  sha256(prev + json.dumps({10 named fields}))       -- a different subset,
                                                                 -- a different encoding

`hash_chain` is part of the trigger's input and is overwritten by the trigger's output, so
the stored row cannot reproduce its own digest — by any verifier, in any language. The
endpoint reported **every** row as tampered on any non-empty table.

The existing tests asserted `len(hash_chain) == 64`. That is true of any SHA-256 output,
including one computed from an algorithm nobody can reproduce, so the control looked tested
and was inverted. An integrity check that always fires is worth exactly as much as one that
never does: both get ignored, and the first real tampering arrives in a report nobody reads.

WHAT THIS ASSERTS, in the order that matters:

  1. a clean chain verifies — the assertion that was missing;
  2. a tampered row is DETECTED — otherwise (1) is satisfied by `return True`;
  3. an inserted row is detected — tamper-evidence covers addition, not just mutation;
  4. legacy rows are reported as unverifiable rather than as violations, because accusing
     them would be false and clearing them would be false;
  5. one tenant's chain verifies without seeing another's — the chain is per organisation.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

VERIFY = "/api/v1/audit/verify"


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


def _write_audit_rows(admin_sync_url, org_id, count=3, action="fs743_probe"):
    """Insert through the TRIGGER, which is the writer under test. Direct SQL rather than
    the API because the API only audits 18 route templates and this needs a known count."""
    ids = []
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        for index in range(count):
            row_id = uuid.uuid4()
            cur.execute(
                "INSERT INTO audit_logs (id, organization_id, action, resource_type, "
                "resource_id, details, hash_chain) "
                "VALUES (%s, %s, %s, 'probe', %s, %s, 'pending')",
                (str(row_id), str(org_id), f"{action}_{index}", str(uuid.uuid4()), "{}"),
            )
            ids.append(row_id)
    conn.close()
    return ids


@pytest_asyncio.fixture
async def audit_rows(admin_sync_url, seeded_orgs):
    ids = _write_audit_rows(admin_sync_url, seeded_orgs["org_a_id"])
    yield ids
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM audit_logs WHERE action LIKE 'fs743_probe%%'")
    conn.close()


class TestTheMeasurementIsReal:
    async def test_the_trigger_stamps_the_current_version(
        self, admin_sync_url, audit_rows
    ):
        """If `hash_version` stops being set to 2, every row silently drops out of the
        verified population and the endpoint reports a clean chain over nothing."""
        conn = _conn(admin_sync_url)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT hash_version, hash_chain FROM audit_logs WHERE id = %s",
                (str(audit_rows[0]),),
            )
            version, digest = cur.fetchone()
        conn.close()
        assert version == 2, f"the trigger wrote hash_version {version}"
        assert digest != "pending", "the trigger did not overwrite the placeholder digest"
        assert len(digest) == 64

    async def test_the_verified_population_is_not_empty(self, client_a, audit_rows):
        response = await client_a.get(VERIFY)
        assert response.status_code == 200, response.text[:200]
        assert response.json()["total_logs"] >= len(audit_rows), (
            "the endpoint verified fewer records than were written — a clean result over "
            "an empty population is the vacuity this whole file exists to prevent"
        )


class TestACleanChainVerifies:
    async def test_it_verifies(self, client_a, audit_rows):
        """THE ASSERTION THAT WAS MISSING FOR THE LIFE OF THE FEATURE."""
        response = await client_a.get(VERIFY)
        assert response.status_code == 200, response.text[:200]
        body = response.json()
        assert body["verified"] is True, (
            f"a chain nobody touched failed verification: {body.get('message')} "
            f"{(body.get('errors') or [])[:2]}"
        )

    async def test_an_empty_chain_verifies(self, client_b):
        """An organisation with no audit rows is verified, not an error."""
        response = await client_b.get(VERIFY)
        assert response.status_code == 200, response.text[:200]
        assert response.json()["verified"] is True


class TestTamperingIsDetected:
    """Every assertion above is satisfied by a verifier that returns True unconditionally.
    These are the ones that make it a control (rule 165)."""

    async def test_a_mutated_row_is_caught(self, client_a, admin_sync_url, audit_rows):
        conn = _conn(admin_sync_url)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE audit_logs SET action = 'fs743_probe_TAMPERED' WHERE id = %s",
                (str(audit_rows[1]),),
            )
        conn.close()

        response = await client_a.get(VERIFY)
        body = response.json()
        assert body["verified"] is False, (
            "an audit row was edited in place and the chain still verified — the control "
            "detects nothing"
        )
        assert str(audit_rows[1]) in {e["log_id"] for e in body["errors"]}, (
            f"the wrong row was blamed: {body['errors']}"
        )

    async def test_a_deleted_row_is_caught(self, client_a, admin_sync_url, audit_rows):
        """Removal breaks the links of everything after it, which is the property a chain
        buys over per-row checksums."""
        conn = _conn(admin_sync_url)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audit_logs WHERE id = %s", (str(audit_rows[0]),))
        conn.close()

        response = await client_a.get(VERIFY)
        assert response.json()["verified"] is False, (
            "a record was deleted from the middle of the chain and verification passed"
        )

    async def test_a_forged_row_is_caught(self, client_a, admin_sync_url, seeded_orgs):
        """An attacker with table access writing a plausible row cannot produce a digest
        that links, because they would have to know the chain state."""
        conn = _conn(admin_sync_url)
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE audit_logs DISABLE TRIGGER audit_log_hash_chain_trigger"
            )
            cur.execute(
                "INSERT INTO audit_logs (id, organization_id, action, resource_type, "
                "hash_chain, hash_version) VALUES (%s, %s, 'fs743_probe_forged', 'probe', "
                "%s, 2)",
                (str(uuid.uuid4()), str(seeded_orgs["org_a_id"]), "0" * 64),
            )
            cur.execute(
                "ALTER TABLE audit_logs ENABLE TRIGGER audit_log_hash_chain_trigger"
            )
        conn.close()

        response = await client_a.get(VERIFY)
        assert response.json()["verified"] is False, (
            "a row inserted with a made-up digest verified successfully"
        )


class TestLegacyRowsAreNotAccused:
    async def test_they_are_reported_rather_than_counted_as_violations(
        self, client_a, admin_sync_url, seeded_orgs, audit_rows
    ):
        """Rows written before migration 069 used an algorithm no verifier can reproduce.
        Calling them tampered is a false accusation; calling them verified is a false
        assurance. They are excluded and named."""
        conn = _conn(admin_sync_url)
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE audit_logs DISABLE TRIGGER audit_log_hash_chain_trigger"
            )
            cur.execute(
                "INSERT INTO audit_logs (id, organization_id, action, resource_type, "
                "hash_chain, hash_version) VALUES (%s, %s, 'fs743_probe_legacy', 'probe', "
                "%s, 1)",
                (str(uuid.uuid4()), str(seeded_orgs["org_a_id"]), "f" * 64),
            )
            cur.execute(
                "ALTER TABLE audit_logs ENABLE TRIGGER audit_log_hash_chain_trigger"
            )
        conn.close()

        response = await client_a.get(VERIFY)
        body = response.json()
        assert body["verified"] is True, (
            f"a legacy record was reported as a violation: {body.get('message')}"
        )
        assert "legacy" in body["message"], (
            f"legacy records were silently dropped from the count instead of named: "
            f"{body['message']}"
        )


class TestTheChainIsPerOrganisation:
    async def test_each_tenant_verifies_its_own(
        self, client_a, client_b, admin_sync_url, seeded_orgs, audit_rows
    ):
        """The chain is partitioned by organisation so a tenant-scoped reader — which is
        every reader this API has — can verify end to end under RLS. A single global chain
        would be unverifiable by anyone who cannot see every row."""
        _write_audit_rows(
            admin_sync_url, seeded_orgs["org_b_id"], count=2, action="fs743_probe_b"
        )
        for client, label in ((client_a, "org A"), (client_b, "org B")):
            body = (await client.get(VERIFY)).json()
            assert body["verified"] is True, (
                f"{label} could not verify its own chain: {body.get('message')}"
            )
