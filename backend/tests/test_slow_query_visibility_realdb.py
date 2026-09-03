"""pg_stat_statements is preloaded and functional, not merely installed (FS-895).

THE FIRST DEFECT. `004_query_optimization.sql`'s `CREATE EXTENSION IF NOT EXISTS
pg_stat_statements` succeeds whether or not the extension is preloaded — it only creates
the SQL objects — and the migration's own guard for building `slow_queries` and the other
monitoring views checks `to_regclass('public.pg_stat_statements')`, which is also
satisfied without preload. So a database that never preloaded the library still gets every
monitoring view built, and each one raises

    ERROR: pg_stat_statements must be loaded via shared_preload_libraries

the first time anyone actually queries it — quietly, because nothing that runs at deploy
time SELECTs from them. `database-ha/cluster.yaml` (CNPG) named only `timescaledb` in
`shared_preload_libraries`, and `base/timescaledb-statefulset.yaml` named neither.

THE SECOND DEFECT, found only by running the full suite rather than this file alone:
`frequent_queries`' unique index was on `queryid` alone, and `pg_stat_statements.queryid`
is only unique per `(userid, dbid, toplevel)` — the same query text run by a different
role or against a different database legitimately produces the same queryid under a
different owner. The first time that happened for real (this suite alone runs queries as
four roles, plus a scratch database from `test_every_migration_can_be_rerun_realdb.py`),
`REFRESH MATERIALIZED VIEW` raised a UniqueViolation and the view never populated.

THE THIRD DEFECT: `refresh_frequent_queries()` was unconditionally
`REFRESH MATERIALIZED VIEW CONCURRENTLY`, and Postgres refuses CONCURRENTLY on a matview
that has never been populated. `frequent_queries` is created WITH NO DATA, so the FIRST
call to this function on any freshly migrated database always raised.

All three are checked against REAL queries and REAL roles, not against manifest or
migration text — reading either would not have caught the first defect (the migration
succeeds either way) or the second (only visible under real multi-role query traffic).
"""
from __future__ import annotations

import re
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parents[2]


class TestExtensionIsPreloadedNotJustInstalled:
    def test_pg_stat_statements_can_actually_be_queried(self, admin_sync_url):
        """The functional check: SELECT from the view. Without preload this raises,
        regardless of whether CREATE EXTENSION succeeded."""
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM pg_stat_statements")
            cur.fetchone()
        finally:
            conn.close()

    def test_the_monitoring_views_are_actually_queryable(self, admin_sync_url):
        """The views 004 builds ARE created either way (rule 296/297's shape: a check
        that is satisfied by something existing rather than something working). Confirm
        each one is queryable, not merely present."""
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            for view in ("slow_queries", "query_performance_trends"):
                cur.execute(f"SELECT count(*) FROM {view}")
                cur.fetchone()
            # frequent_queries is `WITH NO DATA` by design (004's own comment: a
            # materialized view populates at CREATE time, which needs the extension
            # PRELOADED, not just installed) -- it is queryable only after an explicit
            # refresh, which is real usage, not a workaround for this test.
            cur.execute("SELECT refresh_frequent_queries()")
            cur.execute("SELECT count(*) FROM frequent_queries")
            cur.fetchone()
        finally:
            conn.close()


class TestFrequentQueriesKeyMatchesPgStatStatements:
    """The second defect. Reproduced directly rather than by chance: run the same
    literal query text as two different roles, which produces the same queryid under two
    different userids (pg_stat_statements' real key is (userid, dbid, toplevel, queryid)),
    then confirm the refresh does not raise."""

    def test_the_same_query_text_from_two_roles_does_not_collide(self, admin_sync_url):
        """Forces the NON-concurrent refresh path (`REFRESH MATERIALIZED VIEW WITH NO
        DATA` first), not just any refresh: the original crash was building the unique
        index from scratch during a full rewrite. A CONCURRENT refresh (the path taken
        once the view is already populated, which every other test in this file leaves
        it in) diffs against the existing index by row identity instead and does not
        exercise the same failure -- confirmed by mutation-testing this test itself
        against the pre-082 schema, where the concurrent-refresh version of this
        assertion passed for the wrong reason."""
        marker = "/* fs895-duplicate-queryid-probe */ SELECT 1"
        admin_conn = psycopg2.connect(admin_sync_url)
        admin_conn.autocommit = True
        acur = admin_conn.cursor()
        acur.execute("REFRESH MATERIALIZED VIEW frequent_queries WITH NO DATA")
        # A never-before-seen query's FIRST occurrence in pg_stat_statements needs an
        # exclusive lock to insert; the extension is documented to skip that insert
        # (silently, non-fatally) rather than wait if the lock is briefly unavailable.
        # Resetting first empties the hash table immediately before both probes run,
        # which is what made this reproduce reliably instead of depending on whatever
        # else the shared session database happened to be doing at that moment.
        acur.execute("SELECT pg_stat_statements_reset()")
        # tenant_user is provisioned by conftest's _provision_tenant_role for every
        # realdb session -- reuse it rather than creating a third role.
        tenant_dsn = re.sub(r"://[^@]+@", "://tenant_user:tenant_pass@", admin_sync_url)
        tenant_conn = psycopg2.connect(tenant_dsn)
        tenant_conn.autocommit = True
        try:
            # frequent_queries' own definition filters WHERE calls > 100 -- a single
            # execution never appears in the view's result set regardless of the
            # duplicate-key defect, so each role must clear that threshold for this
            # test to exercise anything.
            for conn in (admin_conn, tenant_conn):
                cur = conn.cursor()
                for _ in range(101):
                    cur.execute(marker)
                    cur.fetchone()

            cur = admin_conn.cursor()
            # pg_stat_statements normalizes literal constants (`1` becomes `$1`), so the
            # stored query text is not byte-identical to what was executed -- match on
            # the comment, which normalization leaves alone.
            cur.execute(
                "SELECT COUNT(DISTINCT userid) FROM pg_stat_statements "
                "WHERE query LIKE '%fs895-duplicate-queryid-probe%'"
            )
            distinct_users = cur.fetchone()[0]
            assert distinct_users >= 2, (
                "test setup failed to reproduce two distinct roles recording the same "
                "query text -- this guard cannot exercise the collision it checks for"
            )

            # THE ASSERTION. Before migration 082 this raised
            # psycopg2.errors.UniqueViolation: could not create unique index
            # "idx_frequent_queries_queryid".
            cur.execute("SELECT refresh_frequent_queries()")
        finally:
            admin_conn.close()
            tenant_conn.close()

    def test_the_index_covers_userid_and_dbid(self, admin_sync_url):
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'frequent_queries'"
            )
            defs = [d for (d,) in cur.fetchall()]
        finally:
            conn.close()
        hit = [d for d in defs if "userid" in d and "dbid" in d and "UNIQUE" in d.upper()]
        assert hit, (
            f"no unique index on frequent_queries covers (userid, dbid); found: {defs}. "
            f"queryid alone is not a unique key in pg_stat_statements."
        )


class TestFirstRefreshEverActuallyWorks:
    """The third defect. `frequent_queries` is created WITH NO DATA, so the FIRST call
    to `refresh_frequent_queries()` on any database that only ever ran this migration
    chain always raised -- POST /query-performance/refresh-frequent-queries has never
    worked from a fresh install. Pinned by name so it cannot regress silently."""

    def test_calling_it_on_a_freshly_migrated_database_succeeds(self, admin_sync_url):
        """The suite's own database is session-scoped and other tests in this file
        legitimately refresh this same view first, so "freshly migrated" is forced
        here rather than assumed from run order: drop and recreate the view exactly as
        082 does (WITH NO DATA), then exercise the function against that guaranteed
        first-call state."""
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute("DROP MATERIALIZED VIEW IF EXISTS frequent_queries")
            cur.execute(
                """
                CREATE MATERIALIZED VIEW frequent_queries AS
                SELECT userid, dbid, queryid, query, calls, total_exec_time,
                       mean_exec_time, rows
                FROM pg_stat_statements
                WHERE calls > 100
                ORDER BY calls DESC
                WITH NO DATA
                """
            )
            cur.execute(
                "CREATE UNIQUE INDEX idx_frequent_queries_key "
                "ON frequent_queries(userid, dbid, queryid)"
            )
            cur.execute(
                "SELECT ispopulated FROM pg_matviews WHERE matviewname = 'frequent_queries'"
            )
            assert cur.fetchone()[0] is False, "test setup failed to reproduce the unpopulated state"

            cur.execute("SELECT refresh_frequent_queries()")

            cur.execute(
                "SELECT ispopulated FROM pg_matviews WHERE matviewname = 'frequent_queries'"
            )
            assert cur.fetchone()[0] is True, "refresh ran but the view is still unpopulated"
        finally:
            conn.close()


class TestBothDeployManifestsPreloadIt:
    """Read the manifests too — the realdb checks above prove the mechanism works, these
    prove PRODUCTION actually asks for it, which the realdb fixture cannot see (it sets
    up its own container command in conftest.py, independent of these files)."""

    def test_cnpg_cluster_preloads_it(self):
        text = (REPO / "infrastructure/k8s/database-ha/cluster.yaml").read_text()
        m = re.search(r"shared_preload_libraries:\s*\n((?:\s+-\s*\S+\n)+)", text)
        assert m, "no shared_preload_libraries list found in cluster.yaml"
        libs = re.findall(r"-\s*(\S+)", m.group(1))
        assert "pg_stat_statements" in libs, (
            f"cluster.yaml's shared_preload_libraries is {libs}; pg_stat_statements is "
            f"missing, so the monitoring views 004_query_optimization.sql builds will "
            f"raise on every query in production"
        )
        assert "timescaledb" in libs, "timescaledb must stay listed alongside it"

    def test_base_statefulset_preloads_it(self):
        text = (REPO / "infrastructure/k8s/base/timescaledb-statefulset.yaml").read_text()
        assert "shared_preload_libraries=timescaledb,pg_stat_statements" in text, (
            "base/timescaledb-statefulset.yaml does not set shared_preload_libraries "
            "with both timescaledb and pg_stat_statements named together -- setting it "
            "with only one on the command line REPLACES the image's own preload rather "
            "than appending to it"
        )

    def test_compose_preloads_it(self):
        text = (REPO / "docker-compose.yml").read_text()
        assert "shared_preload_libraries=timescaledb,pg_stat_statements" in text, (
            "docker-compose.yml no longer preloads both libraries together"
        )


class TestSlowQueriesAreLogged:
    def test_log_min_duration_statement_is_set_everywhere(self):
        for path, needle in (
            ("infrastructure/k8s/database-ha/cluster.yaml", "log_min_duration_statement"),
            ("infrastructure/k8s/base/timescaledb-statefulset.yaml", "log_min_duration_statement"),
            ("docker-compose.yml", "log_min_duration_statement"),
        ):
            text = (REPO / path).read_text()
            assert needle in text, (
                f"{path} does not set log_min_duration_statement -- a slow query has "
                f"nowhere to surface except whoever thinks to check pg_stat_statements"
            )
