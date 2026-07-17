-- 023_edge_fleet.sql
-- Edge-fleet agent status, updated on each heartbeat (tasks 16-17).
-- Numbering starts at 023: 001-019 are the integration stack, 020-022 are the
-- fixed-sprints ERP/intake/notifications migrations.

CREATE TABLE IF NOT EXISTS edge_agent_status (
    agent_id                 VARCHAR(64) PRIMARY KEY,
    organization_id          VARCHAR(36),
    agent_version            VARCHAR(32),
    last_seen                TIMESTAMPTZ,

    buffer_pending           INTEGER DEFAULT 0,
    dead_lettered            INTEGER DEFAULT 0,
    dropped                  INTEGER DEFAULT 0,
    active_collectors        INTEGER DEFAULT 0,
    total_collectors         INTEGER DEFAULT 0,
    cert_expires_in_seconds  INTEGER,

    created_at               TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_edge_agent_status_org ON edge_agent_status (organization_id);
CREATE INDEX IF NOT EXISTS idx_edge_agent_status_last_seen ON edge_agent_status (last_seen);
