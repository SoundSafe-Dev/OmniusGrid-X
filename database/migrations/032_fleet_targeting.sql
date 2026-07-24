-- =============================================================================
-- Migration 032: tenant-scoped fleet metadata, dynamic cohorts, and exact previews
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    key VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_sites_org_key UNIQUE (organization_id, key),
    CONSTRAINT uq_sites_org_name UNIQUE (organization_id, name),
    CONSTRAINT uq_sites_id_org UNIQUE (id, organization_id),
    CONSTRAINT ck_sites_key_nonempty CHECK (length(btrim(key)) > 0),
    CONSTRAINT ck_sites_name_nonempty CHECK (length(btrim(name)) > 0)
);

ALTER TABLE workcells
    ADD COLUMN IF NOT EXISTS site_id UUID;

CREATE UNIQUE INDEX IF NOT EXISTS uq_workcells_id_org
    ON workcells(id, organization_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_workcells_site_org'
          AND conrelid = 'workcells'::regclass
    ) THEN
        ALTER TABLE workcells
            ADD CONSTRAINT fk_workcells_site_org
            FOREIGN KEY (site_id, organization_id)
            REFERENCES sites(id, organization_id);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_assets_workcell_org'
          AND conrelid = 'assets'::regclass
    ) THEN
        ALTER TABLE assets
            ADD CONSTRAINT fk_assets_workcell_org
            FOREIGN KEY (workcell_id, organization_id)
            REFERENCES workcells(id, organization_id)
            ON DELETE RESTRICT;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_workcells_org_site
    ON workcells(organization_id, site_id);

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS agent_reported_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS agent_version_valid BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS agent_version_major INTEGER,
    ADD COLUMN IF NOT EXISTS agent_version_minor INTEGER,
    ADD COLUMN IF NOT EXISTS agent_version_patch INTEGER,
    ADD COLUMN IF NOT EXISTS agent_version_prerelease VARCHAR(255);

CREATE UNIQUE INDEX IF NOT EXISTS uq_assets_id_org
    ON assets(id, organization_id);

WITH parsed AS (
    SELECT
        id,
        regexp_match(
            agent_version,
            '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
        ) AS parts
    FROM assets
    WHERE agent_version IS NOT NULL
)
UPDATE assets AS asset
SET
    agent_version_valid = TRUE,
    agent_version_major = parsed.parts[1]::INTEGER,
    agent_version_minor = parsed.parts[2]::INTEGER,
    agent_version_patch = parsed.parts[3]::INTEGER,
    agent_version_prerelease = parsed.parts[4]
FROM parsed
WHERE asset.id = parsed.id
  AND parsed.parts IS NOT NULL
  AND length(parsed.parts[1]) <= 10
  AND length(parsed.parts[2]) <= 10
  AND length(parsed.parts[3]) <= 10
  AND parsed.parts[1]::NUMERIC <= 2147483647
  AND parsed.parts[2]::NUMERIC <= 2147483647
  AND parsed.parts[3]::NUMERIC <= 2147483647
  AND NOT EXISTS (
      SELECT 1
      FROM unnest(string_to_array(COALESCE(parsed.parts[4], ''), '.')) AS identifier
      WHERE identifier ~ '^0[0-9]+$'
  );

ALTER TABLE assets
    DROP CONSTRAINT IF EXISTS ck_assets_agent_semver_components;
ALTER TABLE assets
    ADD CONSTRAINT ck_assets_agent_semver_components CHECK (
        (
            agent_version_valid
            AND agent_version_major IS NOT NULL AND agent_version_major >= 0
            AND agent_version_minor IS NOT NULL AND agent_version_minor >= 0
            AND agent_version_patch IS NOT NULL AND agent_version_patch >= 0
        )
        OR
        (
            NOT agent_version_valid
            AND agent_version_major IS NULL
            AND agent_version_minor IS NULL
            AND agent_version_patch IS NULL
            AND agent_version_prerelease IS NULL
        )
    );

CREATE INDEX IF NOT EXISTS idx_assets_org_agent_semver
    ON assets(
        organization_id,
        agent_version_valid,
        agent_version_major,
        agent_version_minor,
        agent_version_patch
    );

CREATE INDEX IF NOT EXISTS idx_assets_org_agent_reported
    ON assets(organization_id, agent_id, agent_reported_at)
    WHERE agent_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS asset_agent_collectors (
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL,
    collector_type VARCHAR(100) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    running BOOLEAN NOT NULL DEFAULT FALSE,
    heartbeat_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (asset_id, collector_type),
    CONSTRAINT fk_asset_agent_collectors_asset_org
        FOREIGN KEY (asset_id, organization_id)
        REFERENCES assets(id, organization_id)
        ON DELETE CASCADE,
    CONSTRAINT ck_asset_agent_collectors_type
        CHECK (length(btrim(collector_type)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_asset_agent_collectors_org_type
    ON asset_agent_collectors(organization_id, collector_type, asset_id);

CREATE TABLE IF NOT EXISTS fleet_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    key VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    color VARCHAR(32),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fleet_tags_org_key UNIQUE (organization_id, key),
    CONSTRAINT uq_fleet_tags_org_name UNIQUE (organization_id, name),
    CONSTRAINT uq_fleet_tags_id_org UNIQUE (id, organization_id),
    CONSTRAINT ck_fleet_tags_key_nonempty CHECK (length(btrim(key)) > 0),
    CONSTRAINT ck_fleet_tags_name_nonempty CHECK (length(btrim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS asset_fleet_tags (
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL,
    tag_id UUID NOT NULL,
    assigned_by UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (asset_id, tag_id),
    CONSTRAINT fk_asset_fleet_tags_asset_org
        FOREIGN KEY (asset_id, organization_id)
        REFERENCES assets(id, organization_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_asset_fleet_tags_tag_org
        FOREIGN KEY (tag_id, organization_id)
        REFERENCES fleet_tags(id, organization_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asset_fleet_tags_org_tag
    ON asset_fleet_tags(organization_id, tag_id, asset_id);

CREATE TABLE IF NOT EXISTS fleet_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    key VARCHAR(100) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fleet_groups_org_key UNIQUE (organization_id, key),
    CONSTRAINT uq_fleet_groups_org_name UNIQUE (organization_id, name),
    CONSTRAINT uq_fleet_groups_id_org UNIQUE (id, organization_id),
    CONSTRAINT ck_fleet_groups_key_nonempty CHECK (length(btrim(key)) > 0),
    CONSTRAINT ck_fleet_groups_name_nonempty CHECK (length(btrim(name)) > 0)
);

CREATE TABLE IF NOT EXISTS asset_fleet_groups (
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL,
    group_id UUID NOT NULL,
    assigned_by UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (asset_id, group_id),
    CONSTRAINT fk_asset_fleet_groups_asset_org
        FOREIGN KEY (asset_id, organization_id)
        REFERENCES assets(id, organization_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_asset_fleet_groups_group_org
        FOREIGN KEY (group_id, organization_id)
        REFERENCES fleet_groups(id, organization_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asset_fleet_groups_org_group
    ON asset_fleet_groups(organization_id, group_id, asset_id);

CREATE TABLE IF NOT EXISTS fleet_cohorts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    query_version INTEGER NOT NULL DEFAULT 1,
    query JSONB NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_fleet_cohorts_org_name UNIQUE (organization_id, name),
    CONSTRAINT uq_fleet_cohorts_id_org UNIQUE (id, organization_id),
    CONSTRAINT ck_fleet_cohorts_name_nonempty CHECK (length(btrim(name)) > 0),
    CONSTRAINT ck_fleet_cohorts_query_version CHECK (query_version = 1),
    CONSTRAINT ck_fleet_cohorts_query_object
        CHECK (jsonb_typeof(query) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_releases_id_org
    ON agent_releases(id, organization_id);

CREATE TABLE IF NOT EXISTS fleet_target_previews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    release_id UUID NOT NULL,
    selector JSONB NOT NULL,
    ordered_asset_ids JSONB NOT NULL,
    resolved_agents JSONB NOT NULL,
    excluded_assets JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    membership_hash VARCHAR(64) NOT NULL,
    asset_count INTEGER NOT NULL,
    agent_count INTEGER NOT NULL,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_fleet_target_previews_selector_object
        CHECK (jsonb_typeof(selector) = 'object'),
    CONSTRAINT ck_fleet_target_previews_assets_array
        CHECK (jsonb_typeof(ordered_asset_ids) = 'array'),
    CONSTRAINT ck_fleet_target_previews_agents_array
        CHECK (jsonb_typeof(resolved_agents) = 'array'),
    CONSTRAINT ck_fleet_target_previews_excluded_array
        CHECK (jsonb_typeof(excluded_assets) = 'array'),
    CONSTRAINT ck_fleet_target_previews_warnings_array
        CHECK (jsonb_typeof(warnings) = 'array'),
    CONSTRAINT ck_fleet_target_previews_hash
        CHECK (membership_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_fleet_target_previews_counts
        CHECK (asset_count >= 0 AND agent_count >= 0),
    CONSTRAINT uq_fleet_target_previews_id_org
        UNIQUE (id, organization_id),
    CONSTRAINT fk_fleet_target_previews_release_org
        FOREIGN KEY (release_id, organization_id)
        REFERENCES agent_releases(id, organization_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fleet_target_previews_org_expiry
    ON fleet_target_previews(organization_id, expires_at);

ALTER TABLE agent_rollouts
    ADD COLUMN IF NOT EXISTS target_preview_id UUID,
    ADD COLUMN IF NOT EXISTS target_membership_hash VARCHAR(64);

ALTER TABLE agent_rollout_targets
    ADD COLUMN IF NOT EXISTS agent_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS route_asset_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_agent_rollouts_preview_org'
          AND conrelid = 'agent_rollouts'::regclass
    ) THEN
        ALTER TABLE agent_rollouts
            ADD CONSTRAINT fk_agent_rollouts_preview_org
            FOREIGN KEY (target_preview_id, organization_id)
            REFERENCES fleet_target_previews(id, organization_id)
            ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_agent_rollout_targets_route_asset_org'
          AND conrelid = 'agent_rollout_targets'::regclass
    ) THEN
        ALTER TABLE agent_rollout_targets
            ADD CONSTRAINT fk_agent_rollout_targets_route_asset_org
            FOREIGN KEY (route_asset_id, organization_id)
            REFERENCES assets(id, organization_id)
            ON DELETE RESTRICT;
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_rollouts_target_preview
    ON agent_rollouts(target_preview_id)
    WHERE target_preview_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_rollout_targets_agent
    ON agent_rollout_targets(rollout_id, agent_id, wave_index);

CREATE OR REPLACE FUNCTION fleet_prerelease_compare(
    p_left TEXT,
    p_right TEXT
) RETURNS INTEGER
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    left_parts TEXT[];
    right_parts TEXT[];
    left_part TEXT;
    right_part TEXT;
    idx INTEGER;
    max_len INTEGER;
BEGIN
    IF p_left IS NULL AND p_right IS NULL THEN RETURN 0; END IF;
    IF p_left IS NULL THEN RETURN 1; END IF;
    IF p_right IS NULL THEN RETURN -1; END IF;

    left_parts := string_to_array(p_left, '.');
    right_parts := string_to_array(p_right, '.');
    max_len := GREATEST(array_length(left_parts, 1), array_length(right_parts, 1));

    FOR idx IN 1..max_len LOOP
        left_part := left_parts[idx];
        right_part := right_parts[idx];
        IF left_part IS NULL THEN RETURN -1; END IF;
        IF right_part IS NULL THEN RETURN 1; END IF;
        IF left_part ~ '^[0-9]+$' AND right_part ~ '^[0-9]+$' THEN
            IF left_part::NUMERIC < right_part::NUMERIC THEN RETURN -1; END IF;
            IF left_part::NUMERIC > right_part::NUMERIC THEN RETURN 1; END IF;
        ELSIF left_part ~ '^[0-9]+$' THEN
            RETURN -1;
        ELSIF right_part ~ '^[0-9]+$' THEN
            RETURN 1;
        ELSE
            IF left_part COLLATE "C" < right_part COLLATE "C" THEN RETURN -1; END IF;
            IF left_part COLLATE "C" > right_part COLLATE "C" THEN RETURN 1; END IF;
        END IF;
    END LOOP;
    RETURN 0;
END
$$;

-- Every new tenant-owned table fails closed when the tenant GUC is absent.
ALTER TABLE sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON sites;
CREATE POLICY tenant_isolation ON sites FOR ALL
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE asset_agent_collectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_agent_collectors FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON asset_agent_collectors;
CREATE POLICY tenant_isolation ON asset_agent_collectors FOR ALL
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE fleet_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_tags FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON fleet_tags;
CREATE POLICY tenant_isolation ON fleet_tags FOR ALL
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE asset_fleet_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_fleet_tags FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON asset_fleet_tags;
CREATE POLICY tenant_isolation ON asset_fleet_tags FOR ALL
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE fleet_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_groups FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON fleet_groups;
CREATE POLICY tenant_isolation ON fleet_groups FOR ALL
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE asset_fleet_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_fleet_groups FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON asset_fleet_groups;
CREATE POLICY tenant_isolation ON asset_fleet_groups FOR ALL
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE fleet_cohorts ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_cohorts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON fleet_cohorts;
CREATE POLICY tenant_isolation ON fleet_cohorts FOR ALL
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE fleet_target_previews ENABLE ROW LEVEL SECURITY;
ALTER TABLE fleet_target_previews FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON fleet_target_previews;
CREATE POLICY tenant_isolation ON fleet_target_previews FOR ALL
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

COMMIT;
