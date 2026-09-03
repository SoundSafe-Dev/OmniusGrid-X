-- 082: frequent_queries' unique index was on queryid alone, and that is not unique (FS-895).
--
-- FOUND WHILE VERIFYING 081 AGAINST A REAL, BUSY DATABASE, NOT BY READING 004. In
-- isolation the guard passed every time; run as part of the full suite -- thousands of
-- queries, executed by several different roles (`omniusgrid`, `omniusgrid_app`,
-- `omniusgrid_readonly`, `tenant_user`) and, from `test_every_migration_can_be_rerun_
-- realdb.py`, against a second database on the same server -- it failed:
--
--     psycopg2.errors.UniqueViolation: could not create unique index
--     "idx_frequent_queries_queryid"
--     DETAIL: Key (queryid)=(2397681704071010949) is duplicated.
--
-- `pg_stat_statements.queryid` is a hash of the query's normalized text and plan-relevant
-- structure. It is NOT globally unique — the view's actual key is
-- (userid, dbid, toplevel, queryid), because the same query text run by a different role
-- or against a different database legitimately produces the same queryid with a
-- different owner. `frequent_queries` selected only `queryid` and built a unique index on
-- it alone, so the FIRST time two roles or databases happened to run a structurally
-- identical query — normal, unremarkable activity in any real deployment, not an edge
-- case — `REFRESH MATERIALIZED VIEW` raised a unique-violation and the view stayed
-- permanently unpopulated (or, after a partial success, stuck on whatever data an earlier
-- refresh left behind, since the whole statement in refresh_frequent_queries() rolls back
-- as one unit on this error).
--
-- Fixed by carrying userid and dbid through, matching pg_stat_statements' real key.
DO $$
BEGIN
  IF to_regclass('public.frequent_queries') IS NOT NULL THEN
    DROP MATERIALIZED VIEW frequent_queries;

    CREATE MATERIALIZED VIEW frequent_queries AS
    SELECT
        userid,
        dbid,
        queryid,
        query,
        calls,
        total_exec_time,
        mean_exec_time,
        rows
    FROM pg_stat_statements
    WHERE calls > 100
    ORDER BY calls DESC
    WITH NO DATA;

    CREATE UNIQUE INDEX idx_frequent_queries_key
        ON frequent_queries (userid, dbid, queryid);

    GRANT SELECT ON frequent_queries TO omniusgrid;
    COMMENT ON MATERIALIZED VIEW frequent_queries IS 'Most frequently executed queries';
  END IF;
END $$;
