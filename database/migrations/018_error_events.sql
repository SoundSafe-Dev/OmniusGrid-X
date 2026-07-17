-- =============================================================================
-- Migration 018: Error tracking (aggregated unhandled-exception triage)
-- =============================================================================
-- Backs the Error Triage feature: unhandled exceptions are fingerprinted and
-- aggregated in-process, then flushed here. Only metadata is stored — exception
-- type, route TEMPLATE, scrubbed message/traceback samples, counts. No request
-- bodies, headers, query params, or user identity (GDPR-safe by construction).
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS error_events (
    fingerprint        VARCHAR(16) PRIMARY KEY,         -- sha256(type|method|route|frame)[:16]
    exception_type     VARCHAR(255) NOT NULL,
    route              VARCHAR(512) NOT NULL,           -- route TEMPLATE, e.g. /api/v1/assets/{asset_id}
    method             VARCHAR(10)  NOT NULL,
    status_code        INTEGER      NOT NULL DEFAULT 500,
    message_sample     VARCHAR(500),                    -- scrubbed + truncated
    traceback_sample   TEXT,                            -- scrubbed + truncated (latest occurrence)
    total_count        BIGINT       NOT NULL DEFAULT 0,
    regression_count   INTEGER      NOT NULL DEFAULT 0,
    status             VARCHAR(20)  NOT NULL DEFAULT 'open',  -- open | acknowledged | resolved
    status_changed_by  UUID,
    status_changed_at  TIMESTAMPTZ,
    first_seen         TIMESTAMPTZ  NOT NULL,
    last_seen          TIMESTAMPTZ  NOT NULL,
    organization_id    UUID,                            -- org of last occurrence if resolvable
    CONSTRAINT ck_error_events_status
        CHECK (status IN ('open', 'acknowledged', 'resolved')),
    CONSTRAINT fk_error_events_status_changed_by
        FOREIGN KEY (status_changed_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_error_events_last_seen ON error_events (last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_error_events_status    ON error_events (status);

CREATE TABLE IF NOT EXISTS error_event_buckets (
    fingerprint  VARCHAR(16) NOT NULL
        REFERENCES error_events(fingerprint) ON DELETE CASCADE,
    bucket_hour  TIMESTAMPTZ NOT NULL,                  -- truncated to the hour, UTC
    count        BIGINT      NOT NULL DEFAULT 0,
    PRIMARY KEY (fingerprint, bucket_hour)
);

CREATE INDEX IF NOT EXISTS idx_error_buckets_hour ON error_event_buckets (bucket_hour);

COMMIT;
