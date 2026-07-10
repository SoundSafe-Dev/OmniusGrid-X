"""Upgrade-path tests for migration 014 compliance tenant isolation."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "014_compliance_tenant_isolation.sql"
)
FINALIZATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "016_finalize_compliance_tenant_ownership.sql"
)


def test_migration_adds_and_backfills_organization_id(admin_sync_url):
    """Apply migration 014 to a pre-014 schema and verify legacy handling."""
    import psycopg2

    schema = f"migration_014_{uuid4().hex}"
    org_id = uuid4()
    owner_id = uuid4()
    asset_resolved_id = uuid4()
    asset_unresolved_id = uuid4()
    vendor_resolved_id = uuid4()
    vendor_unresolved_id = uuid4()

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(
                """
                CREATE TABLE organizations (
                    id UUID PRIMARY KEY
                );
                CREATE TABLE users (
                    id UUID PRIMARY KEY,
                    organization_id UUID REFERENCES organizations(id)
                );
                CREATE TABLE security_assets (
                    id UUID PRIMARY KEY,
                    asset_type VARCHAR(50) NOT NULL,
                    asset_name VARCHAR(255) NOT NULL,
                    owner_id UUID REFERENCES users(id)
                );
                CREATE TABLE vendor_risk_assessments (
                    id UUID PRIMARY KEY,
                    vendor_name VARCHAR(255) NOT NULL,
                    assessor_id UUID REFERENCES users(id)
                );
                """
            )
            cur.execute(
                "INSERT INTO organizations (id) VALUES (%s);",
                (str(org_id),),
            )
            cur.execute(
                "INSERT INTO users (id, organization_id) VALUES (%s, %s);",
                (str(owner_id), str(org_id)),
            )
            cur.execute(
                "INSERT INTO security_assets "
                "(id, asset_type, asset_name, owner_id) "
                "VALUES (%s, 'software', 'resolved', %s), "
                "(%s, 'hardware', 'unresolved', NULL);",
                (
                    str(asset_resolved_id),
                    str(owner_id),
                    str(asset_unresolved_id),
                ),
            )
            cur.execute(
                "INSERT INTO vendor_risk_assessments "
                "(id, vendor_name, assessor_id) "
                "VALUES (%s, 'resolved', %s), (%s, 'unresolved', NULL);",
                (
                    str(vendor_resolved_id),
                    str(owner_id),
                    str(vendor_unresolved_id),
                ),
            )

            cur.execute(MIGRATION_PATH.read_text())
            cur.execute(f'SET search_path TO "{schema}";')

            cur.execute(
                "SELECT id::text, organization_id::text "
                "FROM security_assets ORDER BY asset_name;"
            )
            asset_orgs = {row[0]: row[1] for row in cur.fetchall()}
            assert asset_orgs[str(asset_resolved_id)] == str(org_id)
            assert asset_orgs[str(asset_unresolved_id)] is None

            cur.execute(
                "SELECT id::text, organization_id::text "
                "FROM vendor_risk_assessments ORDER BY vendor_name;"
            )
            vendor_orgs = {row[0]: row[1] for row in cur.fetchall()}
            assert vendor_orgs[str(vendor_resolved_id)] == str(org_id)
            assert vendor_orgs[str(vendor_unresolved_id)] is None

            cur.execute(
                """
                SELECT table_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name IN (
                      'security_assets',
                      'vendor_risk_assessments'
                  )
                  AND column_name = 'organization_id';
                """,
                (schema,),
            )
            nullable_by_table = dict(cur.fetchall())
            assert nullable_by_table == {
                "security_assets": "YES",
                "vendor_risk_assessments": "YES",
            }

            cur.execute(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relname IN (
                      'security_assets',
                      'vendor_risk_assessments'
                  );
                """,
                (schema,),
            )
            rls_by_table = {
                name: (enabled, forced)
                for name, enabled, forced in cur.fetchall()
            }
            assert rls_by_table == {
                "security_assets": (True, True),
                "vendor_risk_assessments": (True, True),
            }
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public;")
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
        conn.close()


def test_finalization_aborts_while_unresolved_rows_remain(admin_sync_url):
    """Migration 016 must never guess ownership or silently discard rows."""
    import psycopg2

    schema = f"migration_016_blocked_{uuid4().hex}"
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(
                """
                CREATE TABLE security_assets (
                    id UUID PRIMARY KEY,
                    organization_id UUID
                );
                CREATE TABLE vendor_risk_assessments (
                    id UUID PRIMARY KEY,
                    organization_id UUID
                );
                INSERT INTO security_assets (id, organization_id)
                VALUES (%s, NULL);
                """,
                (str(uuid4()),),
            )

            try:
                cur.execute(FINALIZATION_PATH.read_text())
            except psycopg2.errors.RaiseException as exc:
                assert "Complete the manual review" in str(exc)
                cur.execute("ROLLBACK;")
            else:
                raise AssertionError("migration 016 accepted unresolved compliance rows")

            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'security_assets'
                  AND column_name = 'organization_id';
                """,
                (schema,),
            )
            assert cur.fetchone()[0] == "YES"
    finally:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public;")
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
        conn.close()


def test_finalization_enforces_not_null_after_manual_cleanup(admin_sync_url):
    import psycopg2

    schema = f"migration_016_ready_{uuid4().hex}"
    org_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(
                """
                CREATE TABLE security_assets (
                    id UUID PRIMARY KEY,
                    organization_id UUID
                );
                CREATE TABLE vendor_risk_assessments (
                    id UUID PRIMARY KEY,
                    organization_id UUID
                );
                INSERT INTO security_assets (id, organization_id)
                VALUES (%s, %s);
                INSERT INTO vendor_risk_assessments (id, organization_id)
                VALUES (%s, %s);
                """,
                (str(uuid4()), str(org_id), str(uuid4()), str(org_id)),
            )
            cur.execute(FINALIZATION_PATH.read_text())
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(
                """
                SELECT table_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name IN (
                      'security_assets',
                      'vendor_risk_assessments'
                  )
                  AND column_name = 'organization_id';
                """,
                (schema,),
            )
            assert dict(cur.fetchall()) == {
                "security_assets": "NO",
                "vendor_risk_assessments": "NO",
            }
    finally:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public;")
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
        conn.close()
