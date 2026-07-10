-- =============================================================================
-- Migration 027: model artifacts as OTA releases (Task 2)
-- =============================================================================
-- A trained model can be pushed to edge agents through the SAME release +
-- rollout + signing + command-dispatch machinery as config bundles. A model
-- release reuses agent_releases with artifact_type = 'model', model_name set,
-- and no image_tag (K3s image path is config-only). The rollout orchestrator
-- dispatches a 'model_update' command instead of 'agent_update' for these.

BEGIN;

ALTER TABLE agent_releases
    ADD COLUMN IF NOT EXISTS artifact_type VARCHAR(20) NOT NULL DEFAULT 'config',
    ADD COLUMN IF NOT EXISTS model_name VARCHAR(100);

-- Config releases pin a container image; model releases do not.
ALTER TABLE agent_releases
    ALTER COLUMN image_tag DROP NOT NULL;

ALTER TABLE agent_releases
    DROP CONSTRAINT IF EXISTS ck_agent_releases_artifact_type;
ALTER TABLE agent_releases
    ADD CONSTRAINT ck_agent_releases_artifact_type
        CHECK (artifact_type IN ('config', 'model'));

CREATE INDEX IF NOT EXISTS idx_agent_releases_org_artifact_type
    ON agent_releases(organization_id, artifact_type);

COMMIT;
