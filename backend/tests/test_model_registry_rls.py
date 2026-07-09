"""Database-layer RLS tests for the cloud model registry (migration 026).

Connects directly as the non-superuser ``tenant_user`` role and issues raw
SQL — no FastAPI, no ORM. If these pass, Postgres itself rejects cross-tenant
access to ``model_registry`` / ``model_training_runs`` regardless of what the
application code does. Mirrors ``test_tenant_isolation_rls.py``.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import uuid4

import psycopg2


def _tenant_conn(tenant_async_url: str):
    """Open a synchronous psycopg2 connection as ``tenant_user``."""
    parts = urlsplit(tenant_async_url.replace("postgresql+asyncpg", "postgresql"))
    return psycopg2.connect(
        host=parts.hostname,
        port=parts.port,
        user=parts.username,
        password=parts.password,
        dbname=parts.path.lstrip("/"),
    )


def _admin_seed_models(admin_sync_url, org_a_id, org_b_id) -> tuple[str, str]:
    """Seed one model_registry row per org as superuser (bypasses RLS)."""
    model_a_id = str(uuid4())
    model_b_id = str(uuid4())

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO model_registry "
                "(id, organization_id, name, version, artifact_storage_key, "
                " checksum_sha256, feature_contract, metrics) "
                "VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb, '{}'::jsonb), "
                "(%s, %s, %s, %s, %s, %s, '{}'::jsonb, '{}'::jsonb);",
                (
                    model_a_id, str(org_a_id), "anomaly", "v1",
                    f"{org_a_id}/anomaly/v1.pt", "a" * 64,
                    model_b_id, str(org_b_id), "anomaly", "v1",
                    f"{org_b_id}/anomaly/v1.pt", "b" * 64,
                ),
            )
    finally:
        conn.close()
    return model_a_id, model_b_id


class TestModelRegistryRLS:
    """Direct SQL against ``tenant_user`` to prove the 026 policies work."""

    def test_select_without_context_returns_zero_rows(
        self, tenant_async_url, admin_sync_url, seeded_orgs
    ):
        _admin_seed_models(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["org_b_id"]
        )

        conn = _tenant_conn(tenant_async_url)
        try:
            with conn.cursor() as cur:
                # No org context set → policy predicate is NULL → zero rows.
                cur.execute("SELECT count(*) FROM model_registry;")
                count = cur.fetchone()[0]
        finally:
            conn.close()

        assert count == 0, (
            f"Expected 0 model_registry rows without org context, got {count}. "
            "RLS may not be enforcing (check the role is not a superuser)."
        )

    def test_org_a_context_returns_only_org_a_rows(
        self, tenant_async_url, admin_sync_url, seeded_orgs
    ):
        model_a_id, model_b_id = _admin_seed_models(
            admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["org_b_id"]
        )

        conn = _tenant_conn(tenant_async_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.current_org_id', %s, false);",
                    (str(seeded_orgs["org_a_id"]),),
                )
                cur.execute("SELECT id::text FROM model_registry;")
                ids = [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

        assert model_a_id in ids, "Org A's own model row should be visible"
        assert model_b_id not in ids, (
            "Org B's model row leaked through RLS — policy is broken."
        )

    def test_cross_tenant_insert_is_rejected_by_with_check(
        self, tenant_async_url, seeded_orgs
    ):
        """With org A context set, an INSERT for org B must be rejected."""
        conn = _tenant_conn(tenant_async_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.current_org_id', %s, false);",
                    (str(seeded_orgs["org_a_id"]),),
                )
                try:
                    cur.execute(
                        "INSERT INTO model_registry "
                        "(id, organization_id, name, version, "
                        " artifact_storage_key, checksum_sha256, "
                        " feature_contract, metrics) "
                        "VALUES (%s, %s, %s, %s, %s, %s, "
                        "'{}'::jsonb, '{}'::jsonb);",
                        (
                            str(uuid4()),
                            str(seeded_orgs["org_b_id"]),  # foreign org
                            "anomaly", "v2", "x/y.pt", "c" * 64,
                        ),
                    )
                    raised = False
                except psycopg2.Error:
                    raised = True
        finally:
            conn.close()

        assert raised, (
            "Cross-tenant INSERT into model_registry succeeded — WITH CHECK "
            "is not blocking writes to other organizations."
        )

    def test_training_runs_cross_tenant_insert_is_rejected(
        self, tenant_async_url, seeded_orgs
    ):
        conn = _tenant_conn(tenant_async_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.current_org_id', %s, false);",
                    (str(seeded_orgs["org_a_id"]),),
                )
                try:
                    cur.execute(
                        "INSERT INTO model_training_runs "
                        "(id, organization_id, model_name, params, metrics) "
                        "VALUES (%s, %s, %s, '{}'::jsonb, '{}'::jsonb);",
                        (str(uuid4()), str(seeded_orgs["org_b_id"]), "anomaly"),
                    )
                    raised = False
                except psycopg2.Error:
                    raised = True
        finally:
            conn.close()

        assert raised, (
            "Cross-tenant INSERT into model_training_runs succeeded — "
            "WITH CHECK is not blocking."
        )


class TestModelRegistryRLSCoverage:
    """Confirm migration 026 actually enabled RLS on both new tables."""

    def test_new_tables_have_rls_enabled(self, admin_sync_url):
        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' "
                    "AND tablename IN ('model_registry', 'model_training_runs') "
                    "AND rowsecurity = true;"
                )
                got = {row[0] for row in cur.fetchall()}
        finally:
            conn.close()

        assert got == {"model_registry", "model_training_runs"}, (
            f"RLS not enabled on expected tables; got {sorted(got)}"
        )
