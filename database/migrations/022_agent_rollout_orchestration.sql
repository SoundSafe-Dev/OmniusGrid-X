-- =============================================================================
-- Migration 022: Edge-agent OTA rollout orchestration state
-- =============================================================================

BEGIN;

ALTER TABLE agent_rollout_targets
    ADD COLUMN IF NOT EXISTS command_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS rollback_command_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS failure_reason TEXT,
    ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_agent_rollout_targets_command
    ON agent_rollout_targets(command_id)
    WHERE command_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_rollout_targets_rollback_command
    ON agent_rollout_targets(rollback_command_id)
    WHERE rollback_command_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_rollout_targets_status_dispatched
    ON agent_rollout_targets(organization_id, status, dispatched_at);

COMMIT;
