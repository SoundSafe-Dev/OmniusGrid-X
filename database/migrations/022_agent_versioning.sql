-- Migration 022: Edge-agent version and heartbeat visibility.

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS agent_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS agent_version VARCHAR(100),
    ADD COLUMN IF NOT EXISTS agent_config_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS agent_build_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS agent_last_heartbeat TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_assets_org_agent_version
    ON assets(organization_id, agent_version);

CREATE INDEX IF NOT EXISTS idx_assets_org_agent_heartbeat
    ON assets(organization_id, agent_last_heartbeat DESC);
