"""A raw-SQL INSERT must get a timestamp, not NULL (FS-202).

The parity test asserts the DEFAULT exists in the schema. This asserts the
BEHAVIOUR that default is there for: writing a row without going through
SQLAlchemy still stamps created_at, so the row can't vanish from time-ordered
queries and dashboard trends.

Separate from the parity check on purpose — a schema-shape assertion and a
"does the write actually work" assertion fail for different reasons, and the
second is the one that matches how the bug was hit (seed scripts, COPY, worker
bulk inserts, psql fix-ups).
"""
from uuid import uuid4

import psycopg2
import pytest


@pytest.mark.parametrize("table", ["carriers", "yard_trailers", "drivers"])
def test_raw_insert_gets_a_created_at(admin_sync_url, seeded_orgs, table):
    """Insert with the bare minimum of columns; created_at must be populated."""
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # Discover the NOT NULL columns we must supply, so this test doesn't
            # hardcode a schema that migrations may reshape later.
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name=%s
                  AND is_nullable='NO' AND column_default IS NULL
                """,
                (table,),
            )
            required = cur.fetchall()

            cols, vals, params = ["id"], ["%s"], [str(uuid4())]
            for name, dtype in required:
                if name == "id":
                    continue
                cols.append(name)
                vals.append("%s")
                if name == "organization_id":
                    # Must be a REAL org: these tables carry an FK to organizations.
                    params.append(str(seeded_orgs["org_a_id"]))
                elif "uuid" in dtype:
                    params.append(str(uuid4()))
                elif "timestamp" in dtype:
                    params.append("2026-01-01T00:00:00+00:00")
                elif dtype in ("integer", "bigint", "numeric", "double precision"):
                    params.append(0)
                elif dtype == "boolean":
                    params.append(False)
                else:
                    params.append(f"t-{uuid4().hex[:8]}")

            # Deliberately do NOT supply created_at — that is the whole point.
            cur.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)})"
                " RETURNING created_at",
                params,
            )
            created_at = cur.fetchone()[0]

        assert created_at is not None, (
            f"{table}.created_at is NULL after a raw INSERT — the row will be "
            "invisible to every time-ordered query (migration 044)"
        )
    finally:
        conn.close()
