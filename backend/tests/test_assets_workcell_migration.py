from pathlib import Path
from uuid import uuid4


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "013_assets_workcell_required.sql"
)
INITIAL_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "001_init.sql"
)


def test_initial_schema_requires_asset_workcell():
    sql = INITIAL_SCHEMA_PATH.read_text()
    assert "workcell_id UUID NOT NULL REFERENCES workcells(id) ON DELETE RESTRICT" in sql


def test_migration_backfills_legacy_assets_and_enforces_constraint(admin_sync_url):
    import psycopg2

    schema = f"assets_workcell_{uuid4().hex}"
    organization_id = uuid4()
    asset_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute(f'SET search_path TO "{schema}", public')
            cur.execute(
                """
                CREATE TABLE organizations (
                    id UUID PRIMARY KEY,
                    name TEXT NOT NULL
                );
                CREATE TABLE workcells (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    name TEXT NOT NULL,
                    description TEXT
                );
                CREATE TABLE assets (
                    id UUID PRIMARY KEY,
                    organization_id UUID NOT NULL REFERENCES organizations(id),
                    workcell_id UUID REFERENCES workcells(id) ON DELETE SET NULL
                );
                """
            )
            cur.execute(
                "INSERT INTO organizations (id, name) VALUES (%s, 'Legacy tenant')",
                (str(organization_id),),
            )
            cur.execute(
                "INSERT INTO assets (id, organization_id, workcell_id) VALUES (%s, %s, NULL)",
                (str(asset_id), str(organization_id)),
            )

            migration_sql = MIGRATION_PATH.read_text()
            cur.execute(migration_sql)
            cur.execute(migration_sql)

            cur.execute(
                """
                SELECT a.workcell_id, w.name, w.organization_id
                FROM assets a
                JOIN workcells w ON w.id = a.workcell_id
                WHERE a.id = %s
                """,
                (str(asset_id),),
            )
            workcell_id, name, owner_id = cur.fetchone()
            assert workcell_id is not None
            assert name == "Unassigned"
            assert str(owner_id) == str(organization_id)

            cur.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = 'assets'
                  AND column_name = 'workcell_id'
                """,
                (schema,),
            )
            assert cur.fetchone()[0] == "NO"

            cur.execute(
                """
                SELECT rc.delete_rule
                FROM information_schema.referential_constraints rc
                WHERE rc.constraint_schema = %s
                  AND rc.constraint_name = 'assets_workcell_id_fkey'
                """,
                (schema,),
            )
            assert cur.fetchone()[0] == "RESTRICT"
    finally:
        conn.close()
