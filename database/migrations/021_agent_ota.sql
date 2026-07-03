-- =============================================================================
-- Migration 021: Edge-agent OTA releases and rollout control-plane
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS agent_releases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    version VARCHAR(100) NOT NULL,
    channel VARCHAR(50) NOT NULL DEFAULT 'stable',
    image_tag VARCHAR(255) NOT NULL,
    bundle_storage_key TEXT NOT NULL,
    checksum_sha256 VARCHAR(64) NOT NULL,
    signature_ed25519 TEXT NOT NULL,
    signing_key_id VARCHAR(255) NOT NULL,
    release_notes TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_agent_releases_status
        CHECK (status IN ('draft', 'published', 'yanked')),
    CONSTRAINT uq_agent_releases_org_version_channel
        UNIQUE (organization_id, version, channel),
    CONSTRAINT fk_agent_releases_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_releases_created_by
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS agent_rollouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    release_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    target_selector JSONB NOT NULL DEFAULT '{}'::jsonb,
    strategy JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_agent_rollouts_status
        CHECK (status IN (
            'pending', 'paused', 'running', 'completed',
            'cancelled', 'rolled_back', 'failed'
        )),
    CONSTRAINT fk_agent_rollouts_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_rollouts_release
        FOREIGN KEY (release_id) REFERENCES agent_releases(id) ON DELETE RESTRICT,
    CONSTRAINT fk_agent_rollouts_created_by
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS agent_rollout_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rollout_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    asset_id UUID NOT NULL,
    wave_index INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    current_version VARCHAR(100),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_event_at TIMESTAMPTZ,
    CONSTRAINT ck_agent_rollout_targets_status
        CHECK (status IN (
            'pending', 'updating', 'success', 'failed',
            'rolled_back', 'cancelled', 'skipped'
        )),
    CONSTRAINT uq_agent_rollout_targets_rollout_asset
        UNIQUE (rollout_id, asset_id),
    CONSTRAINT fk_agent_rollout_targets_rollout
        FOREIGN KEY (rollout_id) REFERENCES agent_rollouts(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_rollout_targets_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_rollout_targets_asset
        FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_rollout_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rollout_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    asset_id UUID,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_agent_rollout_events_rollout
        FOREIGN KEY (rollout_id) REFERENCES agent_rollouts(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_rollout_events_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_agent_rollout_events_asset
        FOREIGN KEY (asset_id) REFERENCES assets(id) ON DELETE SET NULL
);

ALTER TABLE agent_releases
    ALTER COLUMN channel SET DEFAULT 'stable',
    ALTER COLUMN status SET DEFAULT 'draft',
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE agent_rollouts
    ALTER COLUMN target_selector TYPE JSONB USING target_selector::jsonb,
    ALTER COLUMN target_selector SET DEFAULT '{}'::jsonb,
    ALTER COLUMN strategy TYPE JSONB USING strategy::jsonb,
    ALTER COLUMN strategy SET DEFAULT '{}'::jsonb,
    ALTER COLUMN status SET DEFAULT 'pending',
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE agent_rollout_targets
    ALTER COLUMN wave_index SET DEFAULT 0,
    ALTER COLUMN status SET DEFAULT 'pending',
    ALTER COLUMN attempts SET DEFAULT 0;

ALTER TABLE agent_rollout_events
    ALTER COLUMN detail TYPE JSONB USING detail::jsonb,
    ALTER COLUMN detail SET DEFAULT '{}'::jsonb,
    ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE agent_releases
    DROP CONSTRAINT IF EXISTS ck_agent_releases_status;
ALTER TABLE agent_rollouts
    DROP CONSTRAINT IF EXISTS ck_agent_rollouts_status;
ALTER TABLE agent_rollout_targets
    DROP CONSTRAINT IF EXISTS ck_agent_rollout_targets_status;

ALTER TABLE agent_releases
    ADD CONSTRAINT ck_agent_releases_status
        CHECK (status IN ('draft', 'published', 'yanked'));
ALTER TABLE agent_rollouts
    ADD CONSTRAINT ck_agent_rollouts_status
        CHECK (status IN (
            'pending', 'paused', 'running', 'completed',
            'cancelled', 'rolled_back', 'failed'
        ));
ALTER TABLE agent_rollout_targets
    ADD CONSTRAINT ck_agent_rollout_targets_status
        CHECK (status IN (
            'pending', 'updating', 'success', 'failed',
            'rolled_back', 'cancelled', 'skipped'
        ));

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_releases_org_version_channel
    ON agent_releases(organization_id, version, channel);

CREATE INDEX IF NOT EXISTS idx_agent_releases_org_status
    ON agent_releases(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_releases_org_created
    ON agent_releases(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_rollouts_org_status
    ON agent_rollouts(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_rollouts_release
    ON agent_rollouts(release_id);
CREATE INDEX IF NOT EXISTS idx_agent_rollout_targets_rollout_wave
    ON agent_rollout_targets(rollout_id, wave_index);
CREATE INDEX IF NOT EXISTS idx_agent_rollout_targets_org_asset
    ON agent_rollout_targets(organization_id, asset_id);
CREATE INDEX IF NOT EXISTS idx_agent_rollout_events_rollout_created
    ON agent_rollout_events(rollout_id, created_at);

ALTER TABLE agent_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_releases FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON agent_releases;
CREATE POLICY tenant_isolation ON agent_releases
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

ALTER TABLE agent_rollouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_rollouts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON agent_rollouts;
CREATE POLICY tenant_isolation ON agent_rollouts
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

ALTER TABLE agent_rollout_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_rollout_targets FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON agent_rollout_targets;
CREATE POLICY tenant_isolation ON agent_rollout_targets
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

ALTER TABLE agent_rollout_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_rollout_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON agent_rollout_events;
CREATE POLICY tenant_isolation ON agent_rollout_events
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
