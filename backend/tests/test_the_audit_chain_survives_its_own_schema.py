"""Adding a column to `audit_logs` invalidates every stored digest — say so (FS-743).

The hash chain covers the whole row: the trigger hashes `to_jsonb(NEW) - 'hash_chain'` and
`verify_audit_hash_chain()` re-hashes `to_jsonb(a) - 'hash_chain'`. That is the right
choice for tamper-evidence — a column added tomorrow is integrity-protected the day it
exists, with no field list anybody has to remember to update.

It has one consequence, and it is not obvious from either side of the code. **Adding a
column changes the payload of rows already written**: they gain the new key with a NULL,
their stored digest stops reproducing, and `GET /api/v1/audit/verify` starts reporting the
entire history as tampered. The migration that adds the column is nowhere near the trigger,
its author has no reason to think about hashing, and the failure appears later as an
integrity alert with no cause attached.

That is the same shape as the defect this whole area was fixed for: an integrity control
that cries wolf gets ignored, and then the real tampering arrives in a report nobody reads.

THE REMEDY THIS GUARD ENFORCES. When the column set changes, bump `hash_version` in the
same migration. Old rows move into the honest "unverifiable by construction" bucket that
version 1 already occupies, instead of being accused of tampering they did not suffer.

WHY PINNED HERE RATHER THAN DERIVED. A derived check would compare the schema against
itself and always pass. The pin is the point: it is a statement about what was hashed when
the current version was set, and only a human bumping the version can move it.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

#: The current chain algorithm. Bump BOTH this and the trigger's `NEW.hash_version` when
#: the column set below changes.
CURRENT_HASH_VERSION = 2

#: Every column of `audit_logs` as of migration 069, which is exactly the payload
#: `to_jsonb(row) - 'hash_chain'` produces for version 2.
HASHED_COLUMNS = {
    "action",
    "created_at",
    "details",
    "hash_chain",
    "hash_version",
    "id",
    "ip_address",
    "organization_id",
    "resource_id",
    "resource_type",
    "timestamp",
    "user_agent",
    "user_id",
}


async def _columns(admin_sync_url) -> set[str]:
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'audit_logs'"
        )
        columns = {row[0] for row in cur.fetchall()}
    conn.close()
    return columns


class TestTheMeasurementIsReal:
    async def test_the_table_is_visible(self, admin_sync_url):
        """If the query stops finding the table, the comparison below passes over two
        empty sets and this guard silently stops guarding."""
        columns = await _columns(admin_sync_url)
        assert len(columns) > 5, (
            f"only {len(columns)} columns found for audit_logs; the introspection query "
            f"has broken and every assertion here is vacuous"
        )


class TestTheHashedPayloadHasNotChanged:
    async def test_the_column_set_matches_the_pin(self, admin_sync_url):
        live = await _columns(admin_sync_url)
        added = sorted(live - HASHED_COLUMNS)
        removed = sorted(HASHED_COLUMNS - live)
        assert not added and not removed, (
            f"`audit_logs` changed shape — added {added}, removed {removed}. Every digest "
            f"already stored was computed over the OLD column set, so they will now fail "
            f"verification and `/audit/verify` will report the whole history as tampered.\n\n"
            f"In the same migration that changes the table: bump `NEW.hash_version` in "
            f"`audit_log_hash_chain_trigger` to {CURRENT_HASH_VERSION + 1}, bump "
            f"`CURRENT_HASH_VERSION` here, and update `HASHED_COLUMNS`. That moves the old "
            f"rows into the 'unverifiable by construction' bucket rather than accusing them."
        )

    async def test_the_trigger_stamps_the_pinned_version(self, admin_sync_url):
        """The pin and the trigger have to agree, or the pin is describing an algorithm
        that is not running."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT prosrc FROM pg_proc WHERE proname = 'audit_log_hash_chain_trigger'"
            )
            row = cur.fetchone()
        conn.close()
        assert row is not None, "the hash-chain trigger function is gone"
        assert f"NEW.hash_version = {CURRENT_HASH_VERSION}" in row[0], (
            f"the trigger does not stamp hash_version {CURRENT_HASH_VERSION}; this file's "
            f"pin describes an algorithm that is not the one running"
        )
