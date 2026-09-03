"""shipments indexes the two filter shapes transportation.py actually uses (FS-891).

Migration 043 gave shipments (organization_id, created_at DESC) — the plain tenant-scoped
list. Two other patterns in real use had no index: the shipments list filtering
organization_id + status, and the driver panel filtering driver_id + excluded statuses,
ordered by scheduled_pickup.
"""
from __future__ import annotations

import psycopg2


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


class TestBothAccessPatternsAreIndexed:
    def test_org_status_created_composite_exists(self, admin_sync_url):
        indexes = _index_defs(admin_sync_url, "shipments")
        hit = [
            d for d in indexes.values()
            if "organization_id" in d and "status" in d and "created_at" in d
        ]
        assert hit, (
            f"no index on shipments covering (organization_id, status, created_at); "
            f"found: {list(indexes)}. The shipments list filters both after the org "
            f"predicate is applied."
        )

    def test_driver_scheduled_composite_exists(self, admin_sync_url):
        indexes = _index_defs(admin_sync_url, "shipments")
        hit = [
            d for d in indexes.values()
            if "driver_id" in d and "scheduled_pickup" in d
        ]
        assert hit, (
            f"no index on shipments covering (driver_id, scheduled_pickup); found: "
            f"{list(indexes)}. The driver panel's 'what are they on now' query has "
            f"nothing to use."
        )

    def test_the_planner_can_actually_use_both(self, admin_sync_url):
        """Empty-table fixture (rule 295's shape): force enable_seqscan off and ask
        whether an index-based plan exists at all, rather than whether the cost-based
        planner would choose one on zero rows.

        The org+status+created query names the NEW index specifically, rather than just
        asserting the absence of a sequential scan — the pre-existing
        ix_shipments_org_created already lets the planner avoid a seq scan on the
        organization_id equality alone (with status left as a Filter step), so a bare
        "no Seq Scan" check would pass even without this migration. Same confounded-
        detector shape as rule 297: a check satisfied by something that was already
        there for an unrelated reason."""
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute(
                "EXPLAIN SELECT id FROM shipments WHERE organization_id = "
                "'00000000-0000-0000-0000-000000000000'::uuid AND status = 'planned' "
                "ORDER BY created_at DESC"
            )
            plan_a = "\n".join(r[0] for r in cur.fetchall())
            cur.execute(
                "EXPLAIN SELECT id FROM shipments WHERE driver_id = "
                "'00000000-0000-0000-0000-000000000000'::uuid AND status NOT IN "
                "('delivered', 'cancelled') ORDER BY scheduled_pickup DESC"
            )
            plan_b = "\n".join(r[0] for r in cur.fetchall())
        finally:
            conn.close()
        assert "ix_shipments_org_status_created" in plan_a, (
            f"the planner did not choose the new composite index for org+status+created "
            f"(the pre-existing org_created index alone would still avoid a Seq Scan "
            f"here, which is why this checks the index NAME):\n{plan_a}"
        )
        assert "Seq Scan" not in plan_b, f"driver+scheduled_pickup has no usable index:\n{plan_b}"
