-- =============================================================================
-- Migration 025: Tenant-scoped historian retention and telemetry rollups
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ``Base.metadata.create_all`` creates telemetry as a regular table in some
-- environments. Production already has a hypertable; this is a no-op there.
SELECT create_hypertable(
    'telemetry',
    'time',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

CREATE TABLE IF NOT EXISTS historian_retention_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    metric_name VARCHAR(100) NOT NULL DEFAULT '*',
    hot_retention_days INTEGER NOT NULL DEFAULT 30,
    warm_retention_days INTEGER NOT NULL DEFAULT 365,
    cold_retention_days INTEGER NOT NULL DEFAULT 1825,
    ingestion_priority INTEGER NOT NULL DEFAULT 3,
    ingestion_sample_rate NUMERIC(5, 4) NOT NULL DEFAULT 1.0,
    max_ingest_age_seconds INTEGER NOT NULL DEFAULT 30,
    archival_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_historian_retention_org_metric
        UNIQUE (organization_id, metric_name),
    CONSTRAINT ck_historian_retention_metric
        CHECK (length(btrim(metric_name)) > 0),
    CONSTRAINT ck_historian_retention_days
        CHECK (
            hot_retention_days BETWEEN 1 AND 1825
            AND warm_retention_days BETWEEN hot_retention_days AND 1825
            AND cold_retention_days BETWEEN warm_retention_days AND 3650
        ),
    CONSTRAINT ck_historian_retention_priority
        CHECK (ingestion_priority BETWEEN 1 AND 5),
    CONSTRAINT ck_historian_retention_sample_rate
        CHECK (ingestion_sample_rate > 0 AND ingestion_sample_rate <= 1),
    CONSTRAINT ck_historian_retention_max_age
        CHECK (max_ingest_age_seconds BETWEEN 1 AND 86400),
    CONSTRAINT fk_historian_retention_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_historian_retention_created_by
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_historian_retention_org
    ON historian_retention_policies(organization_id);

ALTER TABLE historian_retention_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE historian_retention_policies FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON historian_retention_policies;
CREATE POLICY tenant_isolation ON historian_retention_policies
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

-- The one-minute aggregate exists in migration 001 in production. Defining it
-- conditionally also supports databases initialized from ORM metadata in tests.
CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_1min (
    time, asset_id, metric_name, avg_value, min_value, max_value, sample_count
)
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    asset_id,
    metric_name,
    avg(value) AS avg_value,
    min(value) AS min_value,
    max(value) AS max_value,
    count(*) AS sample_count
FROM telemetry
GROUP BY bucket, asset_id, metric_name
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_1hour (
    time, asset_id, metric_name, avg_value, min_value, max_value, sample_count
)
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    asset_id,
    metric_name,
    avg(value) AS avg_value,
    min(value) AS min_value,
    max(value) AS max_value,
    count(*) AS sample_count
FROM telemetry
GROUP BY bucket, asset_id, metric_name
WITH NO DATA;

CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_1day (
    time, asset_id, metric_name, avg_value, min_value, max_value, sample_count
)
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    asset_id,
    metric_name,
    avg(value) AS avg_value,
    min(value) AS min_value,
    max(value) AS max_value,
    count(*) AS sample_count
FROM telemetry
GROUP BY bucket, asset_id, metric_name
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_telemetry_1min_asset_metric_time
    ON telemetry_1min(asset_id, metric_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_1hour_asset_metric_time
    ON telemetry_1hour(asset_id, metric_name, time DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_1day_asset_metric_time
    ON telemetry_1day(asset_id, metric_name, time DESC);

SELECT add_continuous_aggregate_policy(
    'telemetry_1min',
    start_offset => INTERVAL '30 days',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);
SELECT add_continuous_aggregate_policy(
    'telemetry_1hour',
    start_offset => INTERVAL '90 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes',
    if_not_exists => TRUE
);
SELECT add_continuous_aggregate_policy(
    'telemetry_1day',
    start_offset => INTERVAL '5 years',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

SELECT add_retention_policy(
    'telemetry_1min', INTERVAL '5 years', if_not_exists => TRUE
);
SELECT add_retention_policy(
    'telemetry_1hour', INTERVAL '10 years', if_not_exists => TRUE
);
SELECT add_retention_policy(
    'telemetry_1day', INTERVAL '10 years', if_not_exists => TRUE
);

-- Raw telemetry can be removed per tenant and metric. Aggregate visibility is
-- enforced by the API's warm/cold windows because Timescale chunks can contain
-- rows from multiple organizations and therefore cannot be dropped per tenant.
CREATE OR REPLACE FUNCTION enforce_tenant_historian_retention(
    p_organization_id UUID,
    p_reference_time TIMESTAMPTZ DEFAULT NOW()
) RETURNS BIGINT AS $$
DECLARE
    deleted_rows BIGINT;
BEGIN
    IF NULLIF(current_setting('app.current_org_id', true), '')::uuid
        IS DISTINCT FROM p_organization_id THEN
        RAISE EXCEPTION 'Tenant context does not match retention request'
            USING ERRCODE = '42501';
    END IF;

    DELETE FROM telemetry AS telemetry_row
    USING assets AS asset
    WHERE telemetry_row.asset_id = asset.id
      AND asset.organization_id = p_organization_id
      AND telemetry_row.time < p_reference_time - make_interval(
          days => COALESCE(
              (
                  SELECT policy.hot_retention_days
                  FROM historian_retention_policies AS policy
                  WHERE policy.organization_id = p_organization_id
                    AND policy.metric_name IN ('*', telemetry_row.metric_name)
                  ORDER BY
                      CASE WHEN policy.metric_name = telemetry_row.metric_name
                          THEN 0 ELSE 1 END
                  LIMIT 1
              ),
              30
          )
      );

    GET DIAGNOSTICS deleted_rows = ROW_COUNT;
    RETURN deleted_rows;
END;
$$ LANGUAGE plpgsql SECURITY INVOKER
SET search_path = public, pg_temp;

COMMENT ON TABLE historian_retention_policies IS
    'Tenant and metric-scoped hot/warm/cold historian retention settings';
COMMENT ON FUNCTION enforce_tenant_historian_retention(UUID, TIMESTAMPTZ) IS
    'Delete raw telemetry outside the active tenant hot-retention window';

-- Migration 001 installs one global raw-telemetry retention policy. A global
-- chunk drop cannot honor longer tenant tiers because each chunk contains data
-- for many organizations, so tenant-aware row retention replaces that policy.
SELECT remove_retention_policy('telemetry', if_exists => TRUE);

CREATE OR REPLACE PROCEDURE enforce_all_tenant_historian_retention(
    job_id INTEGER,
    config JSONB
) LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    tenant RECORD;
BEGIN
    FOR tenant IN SELECT id FROM organizations LOOP
        PERFORM set_config('app.current_org_id', tenant.id::text, true);
        PERFORM enforce_tenant_historian_retention(tenant.id, NOW());
    END LOOP;
    PERFORM set_config('app.current_org_id', '', true);
END;
$$;

REVOKE ALL ON PROCEDURE enforce_all_tenant_historian_retention(INTEGER, JSONB)
    FROM PUBLIC;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM timescaledb_information.jobs
        WHERE proc_schema = 'public'
          AND proc_name = 'enforce_all_tenant_historian_retention'
    ) THEN
        PERFORM add_job(
            'enforce_all_tenant_historian_retention',
            INTERVAL '1 day',
            initial_start => date_trunc('day', NOW()) + INTERVAL '2 hours'
        );
    END IF;
END;
$$;

COMMENT ON PROCEDURE enforce_all_tenant_historian_retention(INTEGER, JSONB) IS
    'Timescale job entry point for daily tenant-aware raw telemetry retention';

COMMIT;
