"""Migration 015 tests for compliance_report_jobs table and RLS."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "015_compliance_report_jobs.sql"
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

    schema = f"migration_015_{uuid4().hex}"
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
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'compliance_report_jobs';
                """,
                (schema,),
            )
            columns = {row[0] for row in cur.fetchall()}
            assert "organization_id" in columns
            assert "report_status" in columns
            assert "delivery_status" in columns
            assert "file_sha256" in columns
    finally:
        conn.close()


def test_migration_upgrade_on_existing_orm_table(admin_sync_url):
    """Applying 015 on a schema that already has the table from create_all is safe."""
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
            for raw in sqlparse.split(sql):
                stmt = sqlparse.format(raw, strip_comments=True).strip()
                if stmt:
                    cur.execute(stmt)
            cur.execute(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = 'compliance_report_jobs';"
            )
            rls, force = cur.fetchone()
            assert rls is True
            assert force is True
            cur.execute(
                """
                SELECT udt_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'compliance_report_jobs'
                  AND column_name = 'recipients';
                """
            )
            assert cur.fetchone()[0] == "jsonb"
            cur.execute(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'compliance_report_jobs'::regclass
                  AND contype = 'c';
                """
            )
            checks = {row[0] for row in cur.fetchall()}
            assert checks == {
                "ck_compliance_report_jobs_framework",
                "ck_compliance_report_jobs_format",
                "ck_compliance_report_jobs_report_status",
                "ck_compliance_report_jobs_delivery_status",
            }
            cur.execute(
                """
                SELECT conname, confdeltype
                FROM pg_constraint
                WHERE conrelid = 'compliance_report_jobs'::regclass
                  AND contype = 'f';
                """
            )
            foreign_keys = dict(cur.fetchall())
            assert foreign_keys["fk_compliance_report_jobs_organization"] == "c"
            assert foreign_keys["fk_compliance_report_jobs_requested_by"] == "n"
    finally:
        conn.close()


def test_constraints_and_indexes(admin_sync_url):
    import psycopg2

    schema = f"migration_015_idx_{uuid4().hex}"
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
                """
                INSERT INTO organizations (id) VALUES (%s);
                INSERT INTO compliance_report_jobs
                (organization_id, framework, format)
                VALUES (%s, 'all', 'json');
                """,
                (str(org_id), str(org_id)),
            )
            with pytest.raises(Exception):
                cur.execute(
                    """
                    INSERT INTO compliance_report_jobs
                    (organization_id, framework, format, report_status)
                    VALUES (%s, 'all', 'json', 'bogus');
                    """,
                    (str(org_id),),
                )
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = %s
                  AND tablename = 'compliance_report_jobs';
                """,
                (schema,),
            )
            indexes = {row[0] for row in cur.fetchall()}
            assert "idx_compliance_report_jobs_org_created" in indexes
            assert "idx_compliance_report_jobs_report_status" in indexes
            assert "idx_compliance_report_jobs_delivery_status" in indexes
    finally:
        conn.close()


def test_rls_without_tenant_context_returns_zero_rows(
    admin_sync_url, tenant_async_url, seeded_orgs
):
    import psycopg2

    org_id = seeded_orgs["org_a_id"]
    job_id = uuid4()
    admin = psycopg2.connect(admin_sync_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(
                """
                INSERT INTO compliance_report_jobs
                (id, organization_id, framework, format)
                VALUES (%s, %s, 'all', 'json');
                """,
                (str(job_id), str(org_id)),
            )
    finally:
        admin.close()

    conn = _tenant_conn(tenant_async_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM compliance_report_jobs;")
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()


def test_tenant_a_cannot_read_or_mutate_tenant_b_jobs(
    admin_sync_url, tenant_async_url, seeded_orgs
):
    import psycopg2

    org_a = seeded_orgs["org_a_id"]
    org_b = seeded_orgs["org_b_id"]
    job_b = uuid4()

    admin = psycopg2.connect(admin_sync_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(
                """
                INSERT INTO compliance_report_jobs
                (id, organization_id, framework, format)
                VALUES (%s, %s, 'soc2', 'pdf');
                """,
                (str(job_b), str(org_b)),
            )
    finally:
        admin.close()

    conn = _tenant_conn(tenant_async_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.current_org_id', %s, false);",
                (str(org_a),),
            )
            cur.execute(
                "SELECT count(*) FROM compliance_report_jobs WHERE id = %s;",
                (str(job_b),),
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                """
                UPDATE compliance_report_jobs
                SET report_status = 'failed'
                WHERE id = %s;
                """,
                (str(job_b),),
            )
            assert cur.rowcount == 0
            cur.execute(
                "DELETE FROM compliance_report_jobs WHERE id = %s;",
                (str(job_b),),
            )
            assert cur.rowcount == 0
    finally:
        conn.close()


def test_orm_contract_matches_migration():
    from sqlalchemy import CheckConstraint
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.dialects.postgresql import JSONB

    from app.db.models import ComplianceReportJob

    table = ComplianceReportJob.__table__
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert checks == {
        "ck_compliance_report_jobs_framework",
        "ck_compliance_report_jobs_format",
        "ck_compliance_report_jobs_report_status",
        "ck_compliance_report_jobs_delivery_status",
    }
    assert isinstance(
        table.c.recipients.type.dialect_impl(postgresql.dialect()),
        JSONB,
    )
    ondelete = {fk.parent.name: fk.ondelete for fk in table.foreign_keys}
    assert ondelete == {
        "organization_id": "CASCADE",
        "requested_by": "SET NULL",
        "schedule_id": "SET NULL",
    }


MIGRATION_017_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "017_scheduled_compliance_reports.sql"
)


def test_migration_017_fresh_schema(admin_sync_url):
    import psycopg2

    schema = f"migration_017_{uuid4().hex}"
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
            cur.execute(MIGRATION_017_PATH.read_text())
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'scheduled_compliance_reports';
                """,
                (schema,),
            )
            columns = {row[0] for row in cur.fetchall()}
            assert "next_run_at" in columns
            assert "frequency" in columns
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'compliance_report_jobs'
                  AND column_name IN ('schedule_id', 'scheduled_for');
                """,
                (schema,),
            )
            assert {row[0] for row in cur.fetchall()} == {"schedule_id", "scheduled_for"}
            cur.execute(MIGRATION_017_PATH.read_text())
            cur.execute(
                """
                SELECT con.conname, con.confdeltype, target.relname
                FROM pg_constraint AS con
                JOIN pg_class AS source ON source.oid = con.conrelid
                JOIN pg_namespace AS ns ON ns.oid = source.relnamespace
                JOIN pg_class AS target ON target.oid = con.confrelid
                JOIN unnest(con.conkey) AS key(attnum) ON TRUE
                JOIN pg_attribute AS attr
                  ON attr.attrelid = source.oid
                 AND attr.attnum = key.attnum
                WHERE ns.nspname = %s
                  AND source.relname = 'compliance_report_jobs'
                  AND con.contype = 'f'
                  AND attr.attname = 'schedule_id';
                """,
                (schema,),
            )
            schedule_foreign_keys = cur.fetchall()
            assert schedule_foreign_keys == [
                (
                    "fk_compliance_report_jobs_schedule",
                    "n",
                    "scheduled_compliance_reports",
                )
            ]
    finally:
        conn.close()
