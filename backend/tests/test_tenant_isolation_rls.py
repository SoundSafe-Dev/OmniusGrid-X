"""Database-layer RLS tests.

Connects directly as the non-superuser ``tenant_user`` role and issues
raw SQL — no FastAPI, no SQLAlchemy ORM, no dependency injection. This
isolates the RLS policies themselves: if these tests pass, the database
is rejecting cross-tenant access regardless of what the application
code does or forgets to do.

Why this matters: the API-level tests in
``test_tenant_isolation_api.py`` could pass simply because the app's
WHERE clauses are doing the filtering. These tests verify the RLS
policies catch cross-tenant access even when the SQL doesn't filter
by ``organization_id`` at all. That's the entire point of having
defense-in-depth at the database layer.
"""

from __future__ import annotations

from uuid import uuid4


def _tenant_conn(tenant_async_url: str):
    """Open a synchronous psycopg2 connection as ``tenant_user``."""
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


def _admin_seed_assets(
    admin_sync_url: str, org_a_id, org_b_id, workcell_a_id, workcell_b_id
) -> tuple[str, str]:
    """Seed one asset per org (as superuser, bypassing RLS). Returns (a_id, b_id).

    ``assets.workcell_id`` is NOT NULL, so each asset references the
    workcell seeded for its org in the ``seeded_orgs`` fixture.
    """
    import psycopg2

    asset_type_id = str(uuid4())
    asset_a_id = str(uuid4())
    asset_b_id = str(uuid4())

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (asset_type_id, "RLSTestType", "test"),
            )
            cur.execute(
                "INSERT INTO assets "
                "(id, organization_id, workcell_id, asset_type_id, name) "
                "VALUES (%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s);",
                (
                    asset_a_id, str(org_a_id), str(workcell_a_id),
                    asset_type_id, "rls-a",
                    asset_b_id, str(org_b_id), str(workcell_b_id),
                    asset_type_id, "rls-b",
                ),
            )
    finally:
        conn.close()
    return asset_a_id, asset_b_id


class TestRLSEnforcement:
    """Direct SQL against ``tenant_user`` to prove policies work."""

    def test_select_without_set_local_returns_zero_rows(
        self, tenant_async_url, admin_sync_url, seeded_orgs
    ):
        _admin_seed_assets(
            admin_sync_url,
            seeded_orgs["org_a_id"], seeded_orgs["org_b_id"],
            seeded_orgs["workcell_a_id"], seeded_orgs["workcell_b_id"],
        )

        conn = _tenant_conn(tenant_async_url)
        try:
            with conn.cursor() as cur:
                # No SET LOCAL → current_setting returns NULL → policy
                # predicate evaluates to NULL (not TRUE) → zero rows.
                cur.execute("SELECT count(*) FROM assets;")
                count = cur.fetchone()[0]
        finally:
            conn.close()

        assert count == 0, (
            f"Expected 0 rows without org context, got {count}. "
            "RLS may not be enforcing — check that the test role is "
            "not a superuser."
        )

    def test_select_with_org_a_context_returns_only_org_a_rows(
        self, tenant_async_url, admin_sync_url, seeded_orgs
    ):
        asset_a_id, asset_b_id = _admin_seed_assets(
            admin_sync_url,
            seeded_orgs["org_a_id"], seeded_orgs["org_b_id"],
            seeded_orgs["workcell_a_id"], seeded_orgs["workcell_b_id"],
        )

        conn = _tenant_conn(tenant_async_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.current_org_id', %s, false);",
                    (str(seeded_orgs["org_a_id"]),),
                )
                cur.execute("SELECT id::text FROM assets ORDER BY name;")
                ids = [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

        assert asset_a_id in ids, "Org A's own row should be visible"
        assert asset_b_id not in ids, (
            "Org B's row leaked through RLS — policy is broken."
        )

    def test_cross_tenant_insert_is_rejected_by_with_check(
        self, tenant_async_url, seeded_orgs
    ):
        """Even with org A's context set, an INSERT for org B must fail."""
        import psycopg2

        conn = _tenant_conn(tenant_async_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT set_config('app.current_org_id', %s, false);",
                    (str(seeded_orgs["org_a_id"]),),
                )

                cur.execute("SELECT id FROM asset_types LIMIT 1;")
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        "INSERT INTO asset_types (id, name, category) "
                        "VALUES (%s, %s, %s) RETURNING id;",
                        (str(uuid4()), "BadInsertType", "test"),
                    )
                    type_id = cur.fetchone()[0]
                else:
                    type_id = row[0]

                try:
                    cur.execute(
                        "INSERT INTO assets "
                        "(id, organization_id, asset_type_id, name) "
                        "VALUES (%s, %s, %s, %s);",
                        (
                            str(uuid4()),
                            str(seeded_orgs["org_b_id"]),  # foreign org
                            str(type_id),
                            "should-fail",
                        ),
                    )
                    raised = False
                except psycopg2.errors.InsufficientPrivilege:
                    raised = True
                except psycopg2.errors.CheckViolation:
                    raised = True
                except psycopg2.Error:
                    raised = True
        finally:
            conn.close()

        assert raised, (
            "Cross-tenant INSERT succeeded — WITH CHECK clause is not "
            "blocking writes to other organizations."
        )


class TestRLSCoverage:
    """Sanity check that the migration enabled RLS on every expected table."""

    def test_strict_rls_tables_have_rls_enabled(self, admin_sync_url):
        """All 23 strict tables + 6 permissive tables should have RLS on."""
        import psycopg2

        expected = {
            # Strict (23)
            "assets", "workcells", "commands", "yard_trailers", "dock_doors",
            "yard_moves", "driver_wait_times", "yard_checkpoints", "carriers",
            "drivers", "shipments", "routes", "load_plans", "freight_charges",
            "dock_appointments", "truck_asset_correlations", "load_quality_logs",
            "task_boards", "task_rules", "actionable_registries",
            "data_correlations", "analysis_sessions", "intake_items",
            # Permissive (6)
            "geotab_trips", "geotab_diagnostics", "geotab_exceptions",
            "audit_logs", "data_processing_records", "integration_configurations",
        }

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' "
                    "AND rowsecurity = true;"
                )
                got = {row[0] for row in cur.fetchall()}
        finally:
            conn.close()

        missing = expected - got
        assert not missing, (
            f"RLS not enabled on expected tables: {sorted(missing)}"
        )

    def test_excluded_tables_have_rls_disabled(self, admin_sync_url):
        """users and api_keys must remain accessible pre-auth — RLS off."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tablename, rowsecurity FROM pg_tables "
                    "WHERE schemaname = 'public' "
                    "AND tablename IN ('users', 'api_keys');"
                )
                rows = dict(cur.fetchall())
        finally:
            conn.close()

        assert rows.get("users") is False, (
            "RLS is enabled on 'users' — login lookup by email would break."
        )
        assert rows.get("api_keys") is False, (
            "RLS is enabled on 'api_keys' — pre-auth key lookup would break."
        )
