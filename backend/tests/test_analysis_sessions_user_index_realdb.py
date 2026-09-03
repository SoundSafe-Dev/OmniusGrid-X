"""analysis_sessions indexes user_id, the predicate its own routes actually use (FS-893).

Migration 043 gave analysis_sessions (organization_id, created_at DESC). Almost every
route in api/analysis_sessions.py filters by user_id instead (fetch, list, delete), several
also filtering status, and neither had an index leading with it.
"""
from __future__ import annotations

import psycopg2


class TestUserIdIsIndexed:
    def test_user_status_composite_exists(self, admin_sync_url):
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'analysis_sessions'"
            )
            defs = [d for (d,) in cur.fetchall()]
        finally:
            conn.close()
        hit = [d for d in defs if "user_id" in d and "status" in d]
        assert hit, (
            f"no index on analysis_sessions covering (user_id, status); found: {defs}. "
            f"Nearly every route in the file filters by user_id, not organization_id."
        )

    def test_the_planner_actually_chooses_it(self, admin_sync_url):
        """Named specifically -- the pre-existing org_created index cannot serve a
        user_id predicate at all (organization_id is its leading column, not user_id),
        so this one is a clean absence rather than the partially-served shape FS-891/892
        had to guard against. Checked anyway, for the same reason: presence of an index
        row is not the same as the planner using it."""
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute(
                "EXPLAIN SELECT id FROM analysis_sessions WHERE user_id = "
                "'00000000-0000-0000-0000-000000000000'::uuid AND status = 'active'"
            )
            plan = "\n".join(r[0] for r in cur.fetchall())
        finally:
            conn.close()
        assert "ix_analysis_sessions_user_status" in plan, (
            f"the planner did not choose the new index:\n{plan}"
        )
