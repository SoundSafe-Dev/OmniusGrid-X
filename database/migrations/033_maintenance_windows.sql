-- =============================================================================
-- Migration 033: timezone-aware maintenance windows and scheduled OTA rollouts
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS maintenance_windows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    site_id UUID,
    name VARCHAR(255) NOT NULL,
    timezone VARCHAR(100) NOT NULL,
    weekdays JSONB NOT NULL,
    local_start_time TIME NOT NULL,
    local_end_time TIME NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_maintenance_windows_org_name
        UNIQUE (organization_id, name),
    CONSTRAINT uq_maintenance_windows_id_org
        UNIQUE (id, organization_id),
    CONSTRAINT fk_maintenance_windows_site_org
        FOREIGN KEY (site_id, organization_id)
        REFERENCES sites(id, organization_id),
    CONSTRAINT ck_maintenance_windows_name_nonempty
        CHECK (length(btrim(name)) > 0),
    CONSTRAINT ck_maintenance_windows_timezone_nonempty
        CHECK (length(btrim(timezone)) > 0),
    CONSTRAINT ck_maintenance_windows_weekdays
        CHECK (
            jsonb_typeof(weekdays) = 'array'
            AND jsonb_array_length(weekdays) BETWEEN 1 AND 7
            AND weekdays <@ '[0, 1, 2, 3, 4, 5, 6]'::jsonb
        ),
    CONSTRAINT ck_maintenance_windows_nonzero_duration
        CHECK (local_start_time <> local_end_time)
);

CREATE INDEX IF NOT EXISTS idx_maintenance_windows_org_site_enabled
    ON maintenance_windows(organization_id, site_id, enabled);

ALTER TABLE agent_rollouts
    ADD COLUMN IF NOT EXISTS scheduled_start_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enforce_maintenance_windows BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pause_reason VARCHAR(40),
    ADD COLUMN IF NOT EXISTS next_eligible_at TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_rollouts_pause_reason'
          AND conrelid = 'agent_rollouts'::regclass
    ) THEN
        ALTER TABLE agent_rollouts
            ADD CONSTRAINT ck_agent_rollouts_pause_reason
            CHECK (
                pause_reason IS NULL
                OR pause_reason IN ('manual', 'maintenance_window')
            );
    END IF;
END
$$;

ALTER TABLE agent_rollout_targets
    ADD COLUMN IF NOT EXISTS site_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_agent_rollout_targets_site_org'
          AND conrelid = 'agent_rollout_targets'::regclass
    ) THEN
        ALTER TABLE agent_rollout_targets
            ADD CONSTRAINT fk_agent_rollout_targets_site_org
            FOREIGN KEY (site_id, organization_id)
            REFERENCES sites(id, organization_id)
            ON DELETE RESTRICT;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_agent_rollouts_schedule_due
    ON agent_rollouts(
        organization_id,
        status,
        next_eligible_at,
        scheduled_start_at
    )
    WHERE status IN ('pending', 'running', 'paused');

CREATE INDEX IF NOT EXISTS idx_agent_rollout_targets_site
    ON agent_rollout_targets(rollout_id, site_id, wave_index);

ALTER TABLE maintenance_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE maintenance_windows FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON maintenance_windows;
CREATE POLICY tenant_isolation ON maintenance_windows FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

COMMIT;
