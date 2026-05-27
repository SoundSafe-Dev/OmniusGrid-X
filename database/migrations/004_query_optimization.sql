-- Query Optimization Foundation
-- Enable pg_stat_statements for query performance monitoring

-- Enable pg_stat_statements extension
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Configure pg_stat_statements
-- Track all queries (not just normalized)
ALTER SYSTEM SET pg_stat_statements.track = all;

-- Track utility commands (not just SELECT/INSERT/UPDATE/DELETE)
ALTER SYSTEM SET pg_stat_statements.track_utility = on;

-- Increase shared memory for pg_stat_statements
-- Default is typically too small for production workloads
ALTER SYSTEM SET pg_stat_statements.max = 10000;

-- Reload configuration to apply changes
SELECT pg_reload_conf();

-- Create view for slow queries (>1 second execution time)
CREATE OR REPLACE VIEW slow_queries AS
SELECT 
    pg_stat_statements.queryid,
    pg_stat_statements.userid,
    pg_stat_statements.dbid,
    pg_stat_statements.query,
    pg_stat_statements.calls,
    pg_stat_statements.total_exec_time,
    pg_stat_statements.mean_exec_time,
    pg_stat_statements.max_exec_time,
    pg_stat_statements.min_exec_time,
    pg_stat_statements.stddev_exec_time,
    pg_stat_statements.rows,
    pg_stat_statements.total_plan_time,
    pg_stat_statements.mean_plan_time,
    pg_stat_statements.max_plan_time,
    pg_stat_statements.min_plan_time,
    pg_stat_statements.stddev_plan_time
FROM pg_stat_statements
WHERE mean_exec_time > 1000  -- 1 second in milliseconds
ORDER BY mean_exec_time DESC;

-- Grant access to monitoring role
GRANT SELECT ON pg_stat_statements TO omniusgrid;
GRANT SELECT ON slow_queries TO omniusgrid;

-- Create function to reset query statistics
CREATE OR REPLACE FUNCTION reset_query_stats()
RETURNS void AS $$
BEGIN
    PERFORM pg_stat_statements_reset();
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute on reset function
GRANT EXECUTE ON FUNCTION reset_query_stats() TO omniusgrid;

-- Create view for query performance by table
CREATE OR REPLACE VIEW query_performance_by_table AS
SELECT 
    schemaname,
    tablename,
    seq_scan,
    seq_tup_read,
    idx_scan,
    idx_tup_fetch,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    n_tup_hot_upd,
    n_live_tup,
    n_dead_tup,
    n_mod_since_analyze,
    last_vacuum,
    last_autovacuum,
    last_analyze,
    last_autoanalyze,
    vacuum_count,
    autovacuum_count,
    analyze_count,
    autoanalyze_count
FROM pg_stat_user_tables
ORDER BY seq_tup_read + idx_tup_fetch DESC;

-- Grant access to monitoring role
GRANT SELECT ON query_performance_by_table TO omniusgrid;

-- Create view for index usage
CREATE OR REPLACE VIEW index_usage_stats AS
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch,
    idx_scan > 0 AS is_used
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;

-- Grant access to monitoring role
GRANT SELECT ON index_usage_stats TO omniusgrid;

-- Create view for missing indexes (potential candidates)
CREATE OR REPLACE VIEW missing_index_candidates AS
SELECT 
    schemaname,
    tablename,
    seq_scan,
    seq_tup_read,
    idx_scan,
    idx_tup_fetch,
    (seq_tup_read::float / GREATEST(seq_scan + idx_scan, 1)) AS seq_tup_read_ratio
FROM pg_stat_user_tables
WHERE seq_scan > 0 
    AND idx_scan = 0
    AND seq_tup_read > 1000
ORDER BY seq_tup_read DESC;

-- Grant access to monitoring role
GRANT SELECT ON missing_index_candidates TO omniusgrid;

-- Create view for query performance trends
CREATE OR REPLACE VIEW query_performance_trends AS
SELECT 
    query,
    calls,
    total_exec_time,
    mean_exec_time,
    stddev_exec_time,
    rows,
    100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0) AS hit_percent
FROM pg_stat_statements
WHERE calls > 10
ORDER BY mean_exec_time DESC;

-- Grant access to monitoring role
GRANT SELECT ON query_performance_trends TO omniusgrid;

-- Create function to analyze query performance
CREATE OR REPLACE FUNCTION analyze_query_performance()
RETURNS TABLE (
    queryid bigint,
    query text,
    calls bigint,
    mean_exec_time numeric,
    max_exec_time numeric,
    stddev_exec_time numeric,
    total_exec_time numeric,
    rows bigint,
    hit_percent numeric,
    performance_rating text
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        qs.queryid,
        qs.query,
        qs.calls,
        qs.mean_exec_time,
        qs.max_exec_time,
        qs.stddev_exec_time,
        qs.total_exec_time,
        qs.rows,
        100.0 * qs.shared_blks_hit / nullif(qs.shared_blks_hit + qs.shared_blks_read, 0) AS hit_percent,
        CASE 
            WHEN qs.mean_exec_time < 10 THEN 'excellent'
            WHEN qs.mean_exec_time < 100 THEN 'good'
            WHEN qs.mean_exec_time < 1000 THEN 'fair'
            ELSE 'poor'
        END AS performance_rating
    FROM pg_stat_statements qs
    WHERE qs.calls > 10
    ORDER BY qs.mean_exec_time DESC;
END;
$$ LANGUAGE plpgsql;

-- Grant execute on analysis function
GRANT EXECUTE ON FUNCTION analyze_query_performance() TO omniusgrid;

-- Create table for query performance history (for trend analysis)
CREATE TABLE IF NOT EXISTS query_performance_history (
    id SERIAL PRIMARY KEY,
    queryid BIGINT,
    query TEXT,
    calls BIGINT,
    mean_exec_time NUMERIC,
    max_exec_time NUMERIC,
    stddev_exec_time NUMERIC,
    total_exec_time NUMERIC,
    rows BIGINT,
    hit_percent NUMERIC,
    performance_rating TEXT,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index on query_performance_history
CREATE INDEX idx_query_perf_history_queryid ON query_performance_history(queryid);
CREATE INDEX idx_query_perf_history_recorded_at ON query_performance_history(recorded_at DESC);

-- Grant access to monitoring role
GRANT SELECT, INSERT ON query_performance_history TO omniusgrid;
GRANT USAGE, SELECT ON SEQUENCE query_performance_history_id_seq TO omniusgrid;

-- Create function to record query performance snapshot
CREATE OR REPLACE FUNCTION record_query_performance_snapshot()
RETURNS void AS $$
BEGIN
    INSERT INTO query_performance_history (
        queryid, query, calls, mean_exec_time, max_exec_time,
        stddev_exec_time, total_exec_time, rows, hit_percent, performance_rating
    )
    SELECT * FROM analyze_query_performance();
END;
$$ LANGUAGE plpgsql;

-- Grant execute on snapshot function
GRANT EXECUTE ON FUNCTION record_query_performance_snapshot() TO omniusgrid;

-- Create materialized view for frequently used queries
CREATE MATERIALIZED VIEW IF NOT EXISTS frequent_queries AS
SELECT 
    queryid,
    query,
    calls,
    total_exec_time,
    mean_exec_time,
    rows
FROM pg_stat_statements
WHERE calls > 100
ORDER BY calls DESC;

-- Create unique index for refresh
CREATE UNIQUE INDEX idx_frequent_queries_queryid ON frequent_queries(queryid);

-- Grant access to monitoring role
GRANT SELECT ON frequent_queries TO omniusgrid;

-- Create function to refresh materialized view
CREATE OR REPLACE FUNCTION refresh_frequent_queries()
RETURNS void AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY frequent_queries;
END;
$$ LANGUAGE plpgsql;

-- Grant execute on refresh function
GRANT EXECUTE ON FUNCTION refresh_frequent_queries() TO omniusgrid;

-- Create view for table bloat (unused space)
CREATE OR REPLACE VIEW table_bloat AS
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) AS index_size,
    n_live_tup,
    n_dead_tup,
    ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_tup_ratio
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Grant access to monitoring role
GRANT SELECT ON table_bloat TO omniusgrid;

-- Create view for cache hit ratio
CREATE OR REPLACE VIEW cache_hit_ratio AS
SELECT 
    sum(heap_blks_read) as heap_read,
    sum(heap_blks_hit) as heap_hit,
    sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) as ratio
FROM pg_statio_user_tables;

-- Grant access to monitoring role
GRANT SELECT ON cache_hit_ratio TO omniusgrid;

-- Comment on objects for documentation
COMMENT ON EXTENSION pg_stat_statements IS 'Track execution statistics of SQL statements';
COMMENT ON VIEW slow_queries IS 'Queries with mean execution time > 1 second';
COMMENT ON VIEW query_performance_by_table IS 'Performance statistics by table';
COMMENT ON VIEW index_usage_stats IS 'Index usage statistics';
COMMENT ON VIEW missing_index_candidates IS 'Tables that may benefit from additional indexes';
COMMENT ON VIEW query_performance_trends IS 'Query performance with cache hit ratio';
COMMENT ON FUNCTION analyze_query_performance() IS 'Analyze query performance with ratings';
COMMENT ON TABLE query_performance_history IS 'Historical query performance data for trend analysis';
COMMENT ON FUNCTION record_query_performance_snapshot() IS 'Record current query performance to history table';
COMMENT ON MATERIALIZED VIEW frequent_queries IS 'Most frequently executed queries';
COMMENT ON FUNCTION refresh_frequent_queries() IS 'Refresh frequent queries materialized view';
COMMENT ON VIEW table_bloat IS 'Table size and bloat statistics';
COMMENT ON VIEW cache_hit_ratio IS 'Overall cache hit ratio';
