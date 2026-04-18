-- TimescaleDB Continuous Aggregates for Feature Vector Generation
-- Run these to create materialized views for ML feature extraction

-- Create continuous aggregate for temperature features
CREATE MATERIALIZED VIEW temp_features_hourly
WITH (timescaledb.continuous) AS
SELECT
    asset_id,
    time_bucket('1 hour', time) as bucket,
    metric_name,
    avg(value) as mean,
    stddev_samp(value) as std,
    min(value) as min_val,
    max(value) as max_val,
    count(*) as sample_count,
    last(value, time) - first(value, time) as delta
FROM telemetry
WHERE metric_name LIKE 'temp_%'
GROUP BY asset_id, bucket, metric_name
WITH NO DATA;

-- Refresh policy for temperature features
SELECT add_continuous_aggregate_policy('temp_features_hourly',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '5 minutes');

-- Create continuous aggregate for performance features
CREATE MATERIALIZED VIEW performance_features_minute
WITH (timescaledb.continuous) AS
SELECT
    asset_id,
    time_bucket('1 minute', time) as bucket,
    metric_name,
    avg(value) as mean,
    max(value) as max_val,
    count(*) as sample_count,
    -- Calculate velocity (rate of change)
    CASE 
        WHEN last(time, time) != first(time, time) 
        THEN (last(value, time) - first(value, time)) / 
             EXTRACT(EPOCH FROM (last(time, time) - first(time, time)))
        ELSE 0
    END as velocity
FROM telemetry
WHERE metric_name IN ('print_speed', 'progress', 'spindle_rpm', 'feed_rate')
GROUP BY asset_id, bucket, metric_name
WITH NO DATA;

SELECT add_continuous_aggregate_policy('performance_features_minute',
    start_offset => INTERVAL '1 week',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');

-- Create continuous aggregate for PackML state durations
CREATE MATERIALIZED VIEW packml_state_hourly
WITH (timescaledb.continuous) AS
SELECT
    asset_id,
    time_bucket('1 hour', state_entered_at) as bucket,
    state,
    sum(duration_seconds) as total_seconds,
    count(*) as transition_count
FROM packml_states
WHERE state_exited_at IS NOT NULL
GROUP BY asset_id, bucket, state
WITH NO DATA;

SELECT add_continuous_aggregate_policy('packml_state_hourly',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '10 minutes');

-- Create efficiency score view
CREATE MATERIALIZED VIEW efficiency_scores_hourly
WITH (timescaledb.continuous) AS
SELECT
    asset_id,
    time_bucket('1 hour', state_entered_at) as bucket,
    -- Calculate productive time ratio (Execute state)
    sum(CASE WHEN state = 'Execute' THEN duration_seconds ELSE 0 END) /
    nullif(sum(duration_seconds), 0) as execute_ratio,
    -- Calculate availability (not Aborted or Stopped)
    sum(CASE WHEN state NOT IN ('Aborted', 'Stopped') THEN duration_seconds ELSE 0 END) /
    nullif(sum(duration_seconds), 0) as availability_ratio
FROM packml_states
WHERE state_exited_at IS NOT NULL
GROUP BY asset_id, bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy('efficiency_scores_hourly',
    start_offset => INTERVAL '1 month',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '10 minutes');
