from pathlib import Path
from uuid import uuid4

import psycopg2
from psycopg2 import sql


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "038_auth_session_hardening.sql"
)


def test_auth_session_migration_upgrades_legacy_rows_idempotently(
    admin_sync_url,
):
    schema = f"auth_upgrade_{uuid4().hex[:10]}"
    user_id = uuid4()
    session_id = uuid4()
    migration_sql = MIGRATION.read_text()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(
                sql.SQL("SET search_path TO {}, public").format(
                    sql.Identifier(schema)
                )
            )
            cur.execute(
                """
                CREATE TABLE users (
                    id UUID PRIMARY KEY
                );
                CREATE TABLE user_sessions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_hash VARCHAR(64) NOT NULL UNIQUE,
                    ip_address VARCHAR(45),
                    user_agent TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    last_activity_at TIMESTAMPTZ DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT true,
                    revoked_at TIMESTAMPTZ,
                    metadata JSONB DEFAULT '{}'
                );
                """
            )
            cur.execute("INSERT INTO users (id) VALUES (%s)", (str(user_id),))
            cur.execute(
                """
                INSERT INTO user_sessions
                    (id, user_id, token_hash, expires_at, metadata)
                VALUES (%s, %s, %s, NOW() + INTERVAL '7 days', %s::jsonb)
                """,
                (
                    str(session_id),
                    str(user_id),
                    "a" * 64,
                    '{"source": "legacy"}',
                ),
            )

            cur.execute(migration_sql)
            cur.execute(migration_sql)
            cur.execute(
                """
                SELECT jti, token_type, revoked_reason, replaced_by_jti,
                       metadata
                FROM user_sessions
                WHERE id = %s
                """,
                (str(session_id),),
            )
            row = cur.fetchone()
            cur.execute("SELECT to_regclass('revoked_tokens')")
            revoked_table = cur.fetchone()[0]

        assert row[0] is not None
        assert row[1] == "refresh"
        assert row[2] is None
        assert row[3] is None
        assert row[4] == {"source": "legacy"}
        assert revoked_table == "revoked_tokens"
    finally:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public")
            cur.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        conn.close()
