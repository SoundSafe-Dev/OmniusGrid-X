"""session_data_sources and session_messages index session_id (FS-889).

Both tables carry a FK on session_id and, before migration 077, no index leading with it —
the only index touching either table is a GIN on `shared_keys::jsonb` (021/033), unrelated
to the join. Every read of a session's messages or data sources filters on this column, and
so does the collapsed form of HARSH's N+1 registered at FS-887.
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


class TestBothChildTablesIndexTheirJoinKey:
    def test_session_data_sources_has_a_session_id_index(self, admin_sync_url):
        indexes = _index_defs(admin_sync_url, "session_data_sources")
        hit = [d for d in indexes.values() if "session_id" in d and "gin" not in d.lower()]
        assert hit, (
            f"no btree index on session_data_sources(session_id); found: "
            f"{list(indexes)}. Every read of a session's data sources is a sequential scan."
        )

    def test_session_messages_has_a_session_id_index(self, admin_sync_url):
        indexes = _index_defs(admin_sync_url, "session_messages")
        hit = [d for d in indexes.values() if "session_id" in d and "gin" not in d.lower()]
        assert hit, (
            f"no btree index on session_messages(session_id); found: "
            f"{list(indexes)}. Every read of a session's message history is a "
            f"sequential scan."
        )

    def test_the_planner_can_actually_use_it(self, admin_sync_url):
        """The fixture's tables are empty, so the cost-based planner would pick a
        sequential scan regardless of what indexes exist (rule 295's shape). Forcing
        enable_seqscan off asks the row-count-independent question: is an index-based
        plan available at all."""
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute("SET LOCAL enable_seqscan = off")
            for table in ("session_data_sources", "session_messages"):
                cur.execute(
                    f"EXPLAIN SELECT id FROM {table} WHERE session_id = "
                    f"'00000000-0000-0000-0000-000000000000'::uuid"
                )
                plan = "\n".join(r[0] for r in cur.fetchall())
                assert "Seq Scan" not in plan, (
                    f"even with sequential scans disabled, {table} still has no usable "
                    f"index on session_id. Plan:\n{plan}"
                )
        finally:
            conn.close()
