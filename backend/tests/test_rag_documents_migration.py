"""Migration 043 tests for rag_documents table and RLS."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "043_rag_documents.sql"
)


def _tenant_conn(tenant_async_url: str):
    import psycopg2
    from urllib.parse import urlsplit

    parts = urlsplit(tenant_async_url.replace("postgresql+asyncpg", "postgresql"))
    return psycopg2.connect(
        host=parts.hostname,
        port=parts.port,
        user=parts.username,
        password=parts.password,
        dbname=parts.path.lstrip("/"),
    )


def test_migration_fresh_schema(admin_sync_url):
    import psycopg2

    schema = f"migration_043_{uuid4().hex}"
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(
                """
                CREATE TABLE organizations (id UUID PRIMARY KEY);
                CREATE TABLE users (id UUID PRIMARY KEY);
                """
            )
            cur.execute(MIGRATION_PATH.read_text())
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'rag_documents';
                """,
                (schema,),
            )
            columns = {row[0]: row[1] for row in cur.fetchall()}
            assert columns["doc_id"] == "text", "doc_id must be TEXT, not uuid"
            for name in (
                "organization_id", "uploaded_by", "filename", "s3_key", "kind",
                "status", "attempts", "num_blocks", "num_chunks", "reason",
                "error", "started_at", "completed_at",
            ):
                assert name in columns
    finally:
        conn.close()


def test_migration_is_reappliable_over_orm_created_table(admin_sync_url):
    """Applying 043 twice, on a schema init_db() already built, is safe."""
    import psycopg2
    import sqlparse
    from sqlalchemy import create_engine

    from app.db.models import Base

    sync_engine = create_engine(admin_sync_url)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            sql = MIGRATION_PATH.read_text()
            for _ in range(2):  # re-appliable
                for raw in sqlparse.split(sql):
                    stmt = sqlparse.format(raw, strip_comments=True).strip()
                    if stmt:
                        cur.execute(stmt)
            cur.execute(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = 'rag_documents';"
            )
            rls, force = cur.fetchone()
            assert rls is True
            assert force is True

            cur.execute(
                """
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'rag_documents'::regclass AND contype = 'c';
                """
            )
            assert {r[0] for r in cur.fetchall()} == {
                "ck_rag_documents_status",
                "ck_rag_documents_kind",
            }

            cur.execute(
                """
                SELECT conname, confdeltype FROM pg_constraint
                WHERE conrelid = 'rag_documents'::regclass AND contype = 'f';
                """
            )
            fks = dict(cur.fetchall())
            assert fks["fk_rag_documents_organization"] == "c"   # CASCADE
            assert fks["fk_rag_documents_uploaded_by"] == "n"    # SET NULL
    finally:
        conn.close()


def test_constraints_and_indexes(admin_sync_url):
    import psycopg2

    schema = f"migration_043_idx_{uuid4().hex}"
    org_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute("CREATE TABLE organizations (id UUID PRIMARY KEY);")
            cur.execute("CREATE TABLE users (id UUID PRIMARY KEY);")
            cur.execute(MIGRATION_PATH.read_text())
            cur.execute(
                "INSERT INTO organizations (id) VALUES (%s);", (str(org_id),)
            )
            cur.execute(
                """
                INSERT INTO rag_documents
                    (organization_id, doc_id, filename, s3_key, kind)
                VALUES (%s, 'doc-1', 'a.txt', 'k/doc-1/a.txt', 'text');
                """,
                (str(org_id),),
            )
            # duplicate (org, doc_id) is rejected
            with pytest.raises(Exception):
                cur.execute(
                    """
                    INSERT INTO rag_documents
                        (organization_id, doc_id, filename, s3_key, kind)
                    VALUES (%s, 'doc-1', 'b.txt', 'k/doc-1/b.txt', 'text');
                    """,
                    (str(org_id),),
                )
            # bogus status is rejected
            with pytest.raises(Exception):
                cur.execute(
                    """
                    INSERT INTO rag_documents
                        (organization_id, doc_id, filename, s3_key, kind, status)
                    VALUES (%s, 'doc-2', 'c.txt', 'k/doc-2/c.txt', 'text', 'bogus');
                    """,
                    (str(org_id),),
                )
            cur.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = %s AND tablename = 'rag_documents';",
                (schema,),
            )
            indexes = {row[0] for row in cur.fetchall()}
            assert "idx_rag_documents_org_created" in indexes
            assert "idx_rag_documents_claimable" in indexes
            assert "idx_rag_documents_stale" in indexes
    finally:
        conn.close()


def test_rls_blocks_no_context_and_cross_tenant(
    admin_sync_url, tenant_async_url, seeded_orgs
):
    import psycopg2

    org_a = seeded_orgs["org_a_id"]
    org_b = seeded_orgs["org_b_id"]

    admin = psycopg2.connect(admin_sync_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rag_documents
                    (organization_id, doc_id, filename, s3_key, kind)
                VALUES (%s, 'b-doc', 'b.txt', 'k/b-doc/b.txt', 'text');
                """,
                (str(org_b),),
            )
    finally:
        admin.close()

    conn = _tenant_conn(tenant_async_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # no tenant context -> zero rows
            cur.execute("SELECT count(*) FROM rag_documents;")
            assert cur.fetchone()[0] == 0

            # org A context -> cannot read, update, or delete org B's row
            cur.execute(
                "SELECT set_config('app.current_org_id', %s, false);", (str(org_a),)
            )
            cur.execute(
                "SELECT count(*) FROM rag_documents WHERE doc_id = 'b-doc';"
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "UPDATE rag_documents SET status = 'failed' WHERE doc_id = 'b-doc';"
            )
            assert cur.rowcount == 0
            cur.execute("DELETE FROM rag_documents WHERE doc_id = 'b-doc';")
            assert cur.rowcount == 0
    finally:
        conn.close()


def test_orm_contract_matches_migration():
    from sqlalchemy import CheckConstraint, UniqueConstraint

    from app.db.models import RagDocument

    table = RagDocument.__table__
    checks = {
        c.name for c in table.constraints if isinstance(c, CheckConstraint)
    }
    assert checks == {"ck_rag_documents_status", "ck_rag_documents_kind"}
    uniques = {
        c.name for c in table.constraints if isinstance(c, UniqueConstraint)
    }
    assert "uq_rag_documents_org_doc" in uniques
    assert {fk.parent.name: fk.ondelete for fk in table.foreign_keys} == {
        "organization_id": "CASCADE",
        "uploaded_by": "SET NULL",
    }
