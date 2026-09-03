-- 081: refresh_frequent_queries() could never populate the view on its first call (FS-895).
--
-- 004_query_optimization.sql created `frequent_queries` `WITH NO DATA` (deliberately —
-- a materialized view populates AT CREATE TIME, which needs pg_stat_statements
-- PRELOADED, not just installed) and its refresh function has always been
-- `REFRESH MATERIALIZED VIEW CONCURRENTLY frequent_queries` unconditionally. Postgres
-- refuses CONCURRENTLY on a matview that has never been populated:
--
--     ERROR: CONCURRENTLY cannot be used when the materialized view is not populated
--
-- So `POST /query-performance/refresh-frequent-queries` (api/query_performance.py:398)
-- has never worked on a database that only ever ran this migration chain — its own
-- try/except reports it as a 503 rather than crashing, so the symptom was "the endpoint
-- doesn't work" with no hint that the fix is a one-line ordering problem, not a broken
-- feature. Found while verifying FS-895's pg_stat_statements preload fix, by actually
-- calling this function rather than reading the migration that defines it.
--
-- Guarded the same way 004 guards everything else here: only touches the view if it
-- exists at all (a database where pg_stat_statements was never installed has no
-- frequent_queries to refresh).
DO $$
BEGIN
  IF to_regclass('public.frequent_queries') IS NOT NULL THEN
    CREATE OR REPLACE FUNCTION refresh_frequent_queries()
    RETURNS void AS $func$
    DECLARE
        already_populated boolean;
    BEGIN
        SELECT ispopulated INTO already_populated
        FROM pg_matviews
        WHERE matviewname = 'frequent_queries';

        IF already_populated THEN
            REFRESH MATERIALIZED VIEW CONCURRENTLY frequent_queries;
        ELSE
            -- First refresh ever: CONCURRENTLY is refused on an unpopulated matview,
            -- and a plain refresh takes a lock the concurrent form would otherwise
            -- avoid — acceptable exactly once, since nothing has queried this view
            -- successfully before this call anyway.
            REFRESH MATERIALIZED VIEW frequent_queries;
        END IF;
    END;
    $func$ LANGUAGE plpgsql;
  END IF;
END $$;
