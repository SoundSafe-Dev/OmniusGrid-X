BEGIN;

ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS jti UUID;
ALTER TABLE user_sessions
    ADD COLUMN IF NOT EXISTS token_type VARCHAR(20) NOT NULL DEFAULT 'refresh';
ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS revoked_reason VARCHAR(100);
ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS replaced_by_jti UUID;

UPDATE user_sessions SET jti = gen_random_uuid() WHERE jti IS NULL;
ALTER TABLE user_sessions ALTER COLUMN jti SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_sessions_jti ON user_sessions(jti);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_active
    ON user_sessions(user_id, is_active);

CREATE TABLE IF NOT EXISTS revoked_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jti UUID NOT NULL UNIQUE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id UUID REFERENCES user_sessions(id) ON DELETE SET NULL,
    token_type VARCHAR(20) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    reason VARCHAR(100),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_revoked_tokens_token_type
        CHECK (token_type IN ('access', 'refresh'))
);

CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires_at
    ON revoked_tokens(expires_at);
CREATE INDEX IF NOT EXISTS idx_revoked_tokens_user_id
    ON revoked_tokens(user_id);

COMMIT;
