-- =============================================================================
-- Migration 049: tenant-scoped user invitations
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS user_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL
        REFERENCES organizations(id) ON DELETE CASCADE,
    normalized_email VARCHAR(320) NOT NULL,
    requested_role VARCHAR(50) NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    expires_at TIMESTAMPTZ NOT NULL,
    delivery_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    last_delivery_attempt_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    delivery_error_code VARCHAR(100),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    accepted_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    accepted_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_invitations_id_org
        UNIQUE (id, organization_id),
    CONSTRAINT ck_user_invitations_email_nonempty
        CHECK (length(trim(normalized_email)) > 0),
    CONSTRAINT ck_user_invitations_role
        CHECK (requested_role IN ('admin', 'operator', 'viewer')),
    CONSTRAINT ck_user_invitations_status
        CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
    CONSTRAINT ck_user_invitations_delivery_status
        CHECK (delivery_status IN ('pending', 'sent', 'failed')),
    CONSTRAINT ck_user_invitations_delivery_attempts
        CHECK (delivery_attempts >= 0),
    CONSTRAINT ck_user_invitations_expiry
        CHECK (expires_at > created_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_invitations_pending_org_email
    ON user_invitations(organization_id, normalized_email)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_user_invitations_org_status_created
    ON user_invitations(organization_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_invitations_pending_expiry
    ON user_invitations(expires_at)
    WHERE status = 'pending';

ALTER TABLE user_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_invitations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON user_invitations;
CREATE POLICY tenant_isolation ON user_invitations FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

COMMIT;
