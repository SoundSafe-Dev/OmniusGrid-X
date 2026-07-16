"""Direct PostgreSQL RLS checks for historian retention policies."""

from urllib.parse import urlsplit
from uuid import uuid4

import psycopg2


def _tenant_conn(tenant_async_url: str):
    parts = urlsplit(tenant_async_url.replace("postgresql+asyncpg", "postgresql"))
    return psycopg2.connect(
        host=parts.hostname,
        port=parts.port,
        user=parts.username,
        password=parts.password,
        dbname=parts.path.lstrip("/"),
    )


def _seed_policies(admin_sync_url, org_a_id, org_b_id):
    ids = (str(uuid4()), str(uuid4()))
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO historian_retention_policies (
                    id, organization_id, metric_name
                ) VALUES (%s, %s, 'metric_a'), (%s, %s, 'metric_b')
                """,
                (ids[0], str(org_a_id), ids[1], str(org_b_id)),
            )
    finally:
        conn.close()
    return ids


def test_historian_retention_rls_fails_closed_without_context(
    tenant_async_url, admin_sync_url, seeded_orgs
):
    _seed_policies(
        admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["org_b_id"]
    )
    conn = _tenant_conn(tenant_async_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM historian_retention_policies")
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()


def test_historian_retention_rls_returns_only_active_tenant(
    tenant_async_url, admin_sync_url, seeded_orgs
):
    policy_a, policy_b = _seed_policies(
        admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["org_b_id"]
    )
    conn = _tenant_conn(tenant_async_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.current_org_id', %s, false)",
                (str(seeded_orgs["org_a_id"]),),
            )
            cur.execute("SELECT id::text FROM historian_retention_policies")
            visible = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    assert policy_a in visible
    assert policy_b not in visible


def test_historian_retention_rls_rejects_cross_tenant_insert(
    tenant_async_url, seeded_orgs
):
    conn = _tenant_conn(tenant_async_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT set_config('app.current_org_id', %s, false)",
                (str(seeded_orgs["org_a_id"]),),
            )
            try:
                cur.execute(
                    """
                    INSERT INTO historian_retention_policies (
                        id, organization_id, metric_name
                    ) VALUES (%s, %s, 'foreign_metric')
                    """,
                    (str(uuid4()), str(seeded_orgs["org_b_id"])),
                )
                rejected = False
            except psycopg2.Error:
                rejected = True
    finally:
        conn.close()
    assert rejected


def test_historian_retention_table_has_forced_rls(admin_sync_url):
    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE oid = 'historian_retention_policies'::regclass
                """
            )
            assert cur.fetchone() == (True, True)
    finally:
        conn.close()


def test_tenant_retention_job_replaces_global_telemetry_retention(admin_sync_url):
    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT proc_name
                FROM timescaledb_information.jobs
                WHERE proc_schema = 'public'
                  AND proc_name IN (
                      'enforce_all_tenant_historian_retention',
                      'policy_retention'
                  )
                  AND (
                      proc_name = 'enforce_all_tenant_historian_retention'
                      OR hypertable_name = 'telemetry'
                  )
                """
            )
            jobs = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
    assert jobs == ["enforce_all_tenant_historian_retention"]
