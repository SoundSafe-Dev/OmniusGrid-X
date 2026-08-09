-- =============================================================================
-- Migration 046: signed wheel artifacts and restart-spanning agent OTA state
-- =============================================================================

BEGIN;

ALTER TABLE agent_releases
    ADD COLUMN IF NOT EXISTS artifact_format VARCHAR(20),
    ADD COLUMN IF NOT EXISTS artifact_filename VARCHAR(255),
    ADD COLUMN IF NOT EXISTS artifact_size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS package_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS minimum_bootstrap_version VARCHAR(100);

ALTER TABLE agent_releases
    DROP CONSTRAINT IF EXISTS ck_agent_releases_artifact_type,
    DROP CONSTRAINT IF EXISTS ck_agent_releases_agent_artifact,
    DROP CONSTRAINT IF EXISTS uq_agent_releases_org_version_channel,
    DROP CONSTRAINT IF EXISTS uq_agent_releases_org_type_version_channel;

DROP INDEX IF EXISTS uq_agent_releases_org_version_channel;

ALTER TABLE agent_releases
    ADD CONSTRAINT ck_agent_releases_artifact_type
        CHECK (artifact_type IN ('config', 'model', 'agent')),
    ADD CONSTRAINT ck_agent_releases_agent_artifact
        CHECK (
            artifact_type <> 'agent'
            OR (
                artifact_format IS NOT NULL
                AND artifact_format = 'wheel'
                AND artifact_filename IS NOT NULL
                AND artifact_size_bytes IS NOT NULL
                AND artifact_size_bytes > 0
                AND package_name IS NOT NULL
                AND package_name = 'opsgrid-agent'
            )
        ),
    ADD CONSTRAINT uq_agent_releases_org_type_version_channel
        UNIQUE (organization_id, artifact_type, version, channel);

CREATE INDEX IF NOT EXISTS idx_agent_releases_org_type_status
    ON agent_releases(organization_id, artifact_type, status);

ALTER TABLE agent_rollout_targets
    ADD COLUMN IF NOT EXISTS attempted_version VARCHAR(100),
    ADD COLUMN IF NOT EXISTS running_version VARCHAR(100),
    ADD COLUMN IF NOT EXISTS local_rollback BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_agent_rollout_targets_running_version
    ON agent_rollout_targets(organization_id, running_version)
    WHERE running_version IS NOT NULL;

COMMIT;
