"""assets.name has an index, and the leading-wildcard search can use it (FS-888).

THE DEFECT. `assets` carried ten indexes and none on `name`, while `api/assets.py` orders
every list call by `Asset.name` and, with a search term, filters
`Asset.name.ilike('%search%')`. A leading wildcard cannot use a plain btree index — the
match could start anywhere in the string — so without `pg_trgm`'s trigram GIN index, that
filter is a guaranteed sequential scan on the largest table in the product, and nothing in
this repo's 75 prior migrations installed `pg_trgm` at all.

Both halves are checked against a REAL database, not by reading the migration file: a
migration can be present and still not do what it claims (the pgcrypto instance in
migration 059 was found precisely because a prior fix was never verified against a live
trigger).
"""
from __future__ import annotations

import psycopg2
import pytest


def _index_defs(admin_sync_url: str, table: str) -> dict[str, str]:
    conn = psycopg2.connect(admin_sync_url)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = %s",
            (table,),
        )
        return {name: definition for name, definition in cur.fetchall()}
    finally:
        conn.close()


class TestTheOrgScopedOrderByHasAnIndex:
    def test_organization_id_name_composite_exists(self, admin_sync_url):
        """The ORDER BY case: organization_id leads (serves RLS + the sort), name
        trails (serves the sort directly)."""
        indexes = _index_defs(admin_sync_url, "assets")
        composite = [
            d for d in indexes.values()
            if "organization_id" in d and "name" in d and "gin" not in d.lower()
        ]
        assert composite, (
            f"no btree index on assets covering (organization_id, name); found: "
            f"{list(indexes)}. Every list call orders by Asset.name within an org, and "
            f"that sort has no index to use."
        )


class TestTheLeadingWildcardSearchHasSomethingToUse:
    def test_pg_trgm_gin_index_exists_when_the_extension_is_available(self, admin_sync_url):
        """A plain btree cannot serve `ilike('%x%')` — the match can start anywhere in
        the string. Only a trigram GIN index makes that plannable."""
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            trgm_installed = cur.fetchone() is not None
        finally:
            conn.close()
        if not trgm_installed:
            pytest.skip("pg_trgm not installed in this environment; migration 076 logs and skips")

        indexes = _index_defs(admin_sync_url, "assets")
        gin = [d for d in indexes.values() if "gin" in d.lower() and "name" in d]
        assert gin, (
            f"pg_trgm is installed but no GIN trigram index exists on assets.name; "
            f"found: {list(indexes)}. The leading-wildcard search is still a sequential "
            f"scan despite the extension being available."
        )

    def test_the_planner_can_actually_use_it(self, admin_sync_url):
        """The index existing is not the same as the planner being ABLE to use it — a
        GIN index built with the wrong operator class, for instance, exists and is
        useless. The table is empty in this fixture, so the cost-based planner would
        pick a sequential scan regardless of which indexes exist (rule 295's shape:
        an assertion that depends on the fixture having rows it does not). Forcing
        `enable_seqscan = off` asks the only question a row-count-independent test
        can: is there a plan that uses the index at all."""
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            if cur.fetchone() is None:
                pytest.skip("pg_trgm not installed in this environment")
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute(
                "EXPLAIN SELECT id FROM assets WHERE name ILIKE %s", ("%pump%",)
            )
            plan = "\n".join(r[0] for r in cur.fetchall())
        finally:
            conn.close()
        assert "Seq Scan" not in plan, (
            f"even with sequential scans disabled, the planner fell back to one — no "
            f"usable index exists for name ILIKE '%...%'. Plan:\n{plan}"
        )
