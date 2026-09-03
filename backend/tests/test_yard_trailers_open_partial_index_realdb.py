"""yard_trailers has a partial index for the open-trailer query (FS-892).

api/yard.py's live-detention query filters check_in_at IS NOT NULL AND check_out_at IS
NULL, scoped by organization_id. Migration 043 gave yard_trailers
(organization_id, check_in_at DESC) — ordered by the org's full history, not narrowed to
the currently-checked-in subset. Same shape as 060_shop_floor_events.sql's partial indexes
for labor_entries and downtime_events's "find the open row" queries.
"""
from __future__ import annotations

import psycopg2


class TestThePartialIndexExists:
    def test_index_exists_with_the_right_predicate(self, admin_sync_url):
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'yard_trailers'"
            )
            defs = [d for (d,) in cur.fetchall()]
        finally:
            conn.close()
        hit = [
            d for d in defs
            if "check_in_at" in d and "check_out_at" in d and "WHERE" in d
        ]
        assert hit, (
            f"no partial index on yard_trailers narrowing to the open-trailer "
            f"predicate; found: {defs}. The live-detention query scans every trailer "
            f"the org has ever had, not just the ones still checked in."
        )

    def test_the_planner_actually_chooses_it(self, admin_sync_url):
        """Named specifically, not just 'no Seq Scan' — FS-891's guard was confounded
        by exactly that weaker check, because a pre-existing index can absorb the
        organization_id equality alone and leave the rest as an unindexed Filter."""
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute(
                "EXPLAIN SELECT id FROM yard_trailers WHERE organization_id = "
                "'00000000-0000-0000-0000-000000000000'::uuid "
                "AND check_in_at IS NOT NULL AND check_out_at IS NULL"
            )
            plan = "\n".join(r[0] for r in cur.fetchall())
        finally:
            conn.close()
        assert "ix_yard_trailers_org_open" in plan, (
            f"the planner did not choose the new partial index:\n{plan}"
        )
