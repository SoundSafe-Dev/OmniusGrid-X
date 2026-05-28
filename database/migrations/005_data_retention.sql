-- Data Retention Policies Foundation
-- Implement tiered storage (hot/warm/cold), automated archival, and compliance-based retention

-- Enable TimescaleDB toolkit for retention policies
CREATE EXTENSION IF NOT EXISTS timescaledb_toolkit;

-- Define retention periods (in days)
-- Hot storage: 7 days (high performance SSD)
-- Warm storage: 30 days (standard SSD)
-- Cold storage: 365 days (S3/object storage)
-- Purge: >365 days

-- Telemetry retention policy
SELECT add_retention_policy('telemetry', INTERVAL '7 days');

-- PackML states retention policy
SELECT add_retention_policy('packml_states', INTERVAL '30 days');

-- Compression policy for telemetry (compress after 7 days)
SELECT add_compression_policy('telemetry', INTERVAL '7 days');

-- Compression policy for packml states (compress after 1 day)
SELECT add_compression_policy('packml_states', INTERVAL '1 day');

-- Create data retention configuration table
CREATE TABLE IF NOT EXISTS data_retention_config (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(255) NOT NULL UNIQUE,
    hot_retention_days INTEGER NOT NULL DEFAULT 7,
    warm_retention_days INTEGER NOT NULL DEFAULT 30,
    cold_retention_days INTEGER NOT NULL DEFAULT 365,
    compliance_retention_days INTEGER, -- Override for compliance requirements
    compliance_standard VARCHAR(100), -- e.g., 'GDPR', 'SOC2', 'ISO27001'
    archival_enabled BOOLEAN DEFAULT TRUE,
    archival_destination VARCHAR(255) DEFAULT 's3://omniusgrid-archive',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default retention configurations
INSERT INTO data_retention_config (table_name, hot_retention_days, warm_retention_days, cold_retention_days) VALUES
('telemetry', 7, 30, 365),
('packml_states', 30, 90, 365),
('alarms', 90, 365, 1825), -- 5 years for alarms (compliance)
('commands', 365, 1825, 3650) -- 10 years for commands (audit trail)
ON CONFLICT (table_name) DO NOTHING;

-- Create function to update retention policy
CREATE OR REPLACE FUNCTION update_retention_policy(
    p_table_name VARCHAR(255),
    p_retention_days INTEGER
) RETURNS void AS $$
BEGIN
    -- Remove existing policy
    SELECT remove_retention_policy(p_table_name);
    
    -- Add new policy
    SELECT add_retention_policy(p_table_name, INTERVAL '1 day' * p_retention_days);
    
    -- Update configuration
    UPDATE data_retention_config
    SET hot_retention_days = p_retention_days,
        updated_at = NOW()
    WHERE table_name = p_table_name;
END;
$$ LANGUAGE plpgsql;

-- Create function for automated archival to cold storage
CREATE OR REPLACE FUNCTION archive_to_cold_storage()
RETURNS TABLE (
    table_name VARCHAR(255),
    archived_rows BIGINT,
    archival_time TIMESTAMPTZ
) AS $$
DECLARE
    config_record RECORD;
    archive_count BIGINT;
BEGIN
    FOR config_record IN 
        SELECT table_name, warm_retention_days, archival_enabled, archival_destination
        FROM data_retention_config
        WHERE archival_enabled = TRUE
    LOOP
        -- Archive data older than warm retention period
        -- This is a placeholder - actual implementation depends on archival destination
        -- For S3, you would use pg_dump or a similar tool
        
        -- Log archival
        RAISE NOTICE 'Archiving % older than % days to %', 
            config_record.table_name, 
            config_record.warm_retention_days,
            config_record.archival_destination;
        
        archive_count := 0; -- Placeholder
        
        RETURN QUERY SELECT
            config_record.table_name,
            archive_count,
            NOW();
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Create function for automated data purging
CREATE OR REPLACE FUNCTION purge_old_data()
RETURNS TABLE (
    table_name VARCHAR(255),
    purged_rows BIGINT,
    purge_time TIMESTAMPTZ
) AS $$
DECLARE
    config_record RECORD;
    purge_count BIGINT;
    cutoff_date TIMESTAMPTZ;
BEGIN
    FOR config_record IN 
        SELECT table_name, cold_retention_days, compliance_retention_days
        FROM data_retention_config
    LOOP
        -- Use compliance retention if set, otherwise use cold retention
        IF config_record.compliance_retention_days IS NOT NULL THEN
            cutoff_date := NOW() - INTERVAL '1 day' * config_record.compliance_retention_days;
        ELSE
            cutoff_date := NOW() - INTERVAL '1 day' * config_record.cold_retention_days;
        END IF;
        
        -- Delete old data (actual implementation depends on table structure)
        -- This is a placeholder - you would implement table-specific deletion logic
        
        purge_count := 0; -- Placeholder
        
        RETURN QUERY SELECT
            config_record.table_name,
            purge_count,
            NOW();
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Create view for retention status
CREATE OR REPLACE VIEW retention_status AS
SELECT 
    t.table_name,
    t.hot_retention_days,
    t.warm_retention_days,
    t.cold_retention_days,
    t.compliance_retention_days,
    t.compliance_standard,
    t.archival_enabled,
    t.archival_destination,
    pg_size_pretty(pg_total_relation_size(t.table_name::regclass)) AS current_size,
    (SELECT COUNT(*) FROM pg_stat_user_tables WHERE schemaname || '.' || tablename = t.table_name) AS has_stats
FROM data_retention_config t;

-- Grant access to monitoring role
GRANT SELECT ON retention_status TO omniusgrid;
GRANT SELECT ON data_retention_config TO omniusgrid;
GRANT EXECUTE ON FUNCTION update_retention_policy(VARCHAR, INTEGER) TO omniusgrid;
GRANT EXECUTE ON FUNCTION archive_to_cold_storage() TO omniusgrid;
GRANT EXECUTE ON FUNCTION purge_old_data() TO omniusgrid;

-- Create GDPR-specific retention configuration
INSERT INTO data_retention_config (table_name, hot_retention_days, warm_retention_days, cold_retention_days, compliance_retention_days, compliance_standard) VALUES
('user_audit_logs', 30, 90, 365, 2555, 'GDPR'), -- 7 years for GDPR
('personal_data', 30, 90, 365, 2555, 'GDPR')
ON CONFLICT (table_name) DO NOTHING;

-- Create SOC2-specific retention configuration
INSERT INTO data_retention_config (table_name, hot_retention_days, warm_retention_days, cold_retention_days, compliance_retention_days, compliance_standard) VALUES
('access_logs', 90, 365, 1825, 3650, 'SOC2'), -- 10 years for SOC2
('change_logs', 90, 365, 1825, 3650, 'SOC2')
ON CONFLICT (table_name) DO NOTHING;

-- Create continuous aggregates for long-term data retention
-- This allows querying aggregated data while keeping raw data for shorter periods

-- Hourly OEE aggregates (keep for 1 year)
CREATE MATERIALIZED VIEW oee_hourly WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', state_entered_at) AS hour,
    asset_id,
    COUNT(*) AS state_changes,
    SUM(EXTRACT(EPOCH FROM (state_exited_at - state_entered_at))) AS total_seconds,
    AVG(EXTRACT(EPOCH FROM (state_exited_at - state_entered_at))) AS avg_seconds_per_state
FROM packml_states
WHERE state_exited_at IS NOT NULL
GROUP BY hour, asset_id;

-- Set retention for hourly aggregates (1 year)
SELECT add_retention_policy('oee_hourly', INTERVAL '365 days');

-- Daily OEE aggregates (keep for 5 years)
CREATE MATERIALIZED VIEW oee_daily WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 day', state_entered_at) AS day,
    asset_id,
    COUNT(*) AS state_changes,
    SUM(EXTRACT(EPOCH FROM (state_exited_at - state_entered_at))) AS total_seconds,
    AVG(EXTRACT(EPOCH FROM (state_exited_at - state_entered_at))) AS avg_seconds_per_state
FROM packml_states
WHERE state_exited_at IS NOT NULL
GROUP BY day, asset_id;

-- Set retention for daily aggregates (5 years)
SELECT add_retention_policy('oee_daily', INTERVAL '1825 days');

-- Refresh policy for continuous aggregates
SELECT add_continuous_aggregate_policy('oee_hourly', 
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour');

SELECT add_continuous_aggregate_policy('oee_daily',
    start_offset => INTERVAL '1 day',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day');

-- Create function to check compliance retention requirements
CREATE OR REPLACE FUNCTION check_compliance_retention()
RETURNS TABLE (
    table_name VARCHAR(255),
    compliance_standard VARCHAR(100),
    required_retention_days INTEGER,
    current_retention_days INTEGER,
    is_compliant BOOLEAN,
    recommendation TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        t.table_name,
        t.compliance_standard,
        t.compliance_retention_days AS required_retention_days,
        t.cold_retention_days AS current_retention_days,
        t.cold_retention_days >= COALESCE(t.compliance_retention_days, 0) AS is_compliant,
        CASE 
            WHEN t.cold_retention_days < COALESCE(t.compliance_retention_days, 0) 
            THEN 'Increase cold_retention_days to meet ' || t.compliance_standard || ' requirements'
            ELSE 'Retention policy compliant with ' || t.compliance_standard
        END AS recommendation
    FROM data_retention_config t
    WHERE t.compliance_standard IS NOT NULL;
END;
$$ LANGUAGE plpgsql;

-- Grant access to compliance check function
GRANT EXECUTE ON FUNCTION check_compliance_retention() TO omniusgrid;

-- Comment on objects for documentation
COMMENT ON TABLE data_retention_config IS 'Configuration for data retention policies per table';
COMMENT ON FUNCTION update_retention_policy(VARCHAR, INTEGER) IS 'Update retention policy for a table';
COMMENT ON FUNCTION archive_to_cold_storage() IS 'Archive data to cold storage (S3)';
COMMENT ON FUNCTION purge_old_data() IS 'Purge data exceeding retention period';
COMMENT ON VIEW retention_status IS 'Current status of data retention policies';
COMMENT ON MATERIALIZED VIEW oee_hourly IS 'Hourly OEE aggregates for long-term retention';
COMMENT ON MATERIALIZED VIEW oee_daily IS 'Daily OEE aggregates for long-term retention';
COMMENT ON FUNCTION check_compliance_retention() IS 'Check if retention policies meet compliance requirements';
