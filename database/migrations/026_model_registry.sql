-- =============================================================================
-- Migration 026: Cloud model registry + training runs (MLOps producer side)
-- =============================================================================
-- Tenant-scoped registry for models trained in the cloud (anomaly,
-- oee_forecast, tactical-engine, ...) plus the training-run provenance that
-- produced them. Artifacts (TorchScript .pt) live on disk under
-- MODEL_STORAGE_PATH; this table stores metadata + checksum + feature contract.
-- Serves the {version, download_url, sha256_hash} shape the edge MLOps client
-- (services/mlops_pipeline.py) already polls via /api/v1/models/{name}/latest.

BEGIN;

CREATE TABLE IF NOT EXISTS model_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name VARCHAR(100) NOT NULL,
    version VARCHAR(100) NOT NULL,
    framework VARCHAR(50) NOT NULL DEFAULT 'torchscript',
    artifact_storage_key TEXT NOT NULL,
    checksum_sha256 VARCHAR(64) NOT NULL,
    feature_contract JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    training_run_id UUID,
    release_notes TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_model_registry_status
        CHECK (status IN ('draft', 'published', 'yanked')),
    CONSTRAINT uq_model_registry_org_name_version
        UNIQUE (organization_id, name, version),
    CONSTRAINT fk_model_registry_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_model_registry_created_by
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS model_training_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    model_name VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    dataset_window_start TIMESTAMPTZ,
    dataset_window_end TIMESTAMPTZ,
    sample_count INTEGER,
    produced_model_id UUID,
    error TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    CONSTRAINT ck_model_training_runs_status
        CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT fk_model_training_runs_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_model_training_runs_produced_model
        FOREIGN KEY (produced_model_id) REFERENCES model_registry(id) ON DELETE SET NULL,
    CONSTRAINT fk_model_training_runs_created_by
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_model_registry_org_name_version
    ON model_registry(organization_id, name, version);
CREATE INDEX IF NOT EXISTS idx_model_registry_org_name_status
    ON model_registry(organization_id, name, status);
CREATE INDEX IF NOT EXISTS idx_model_registry_org_created
    ON model_registry(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_model_training_runs_org_status
    ON model_training_runs(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_model_training_runs_org_model_created
    ON model_training_runs(organization_id, model_name, created_at DESC);

ALTER TABLE model_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_registry FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON model_registry;
CREATE POLICY tenant_isolation ON model_registry
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

ALTER TABLE model_training_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_training_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON model_training_runs;
CREATE POLICY tenant_isolation ON model_training_runs
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

COMMIT;
