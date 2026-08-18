-- Multifactor authentication for local accounts (FS-750).
--
-- WHY THIS TABLE EXISTS. NIST SP 800-171 3.5.3 requires MFA for local AND network access to
-- privileged accounts, and for network access to non-privileged ones. It is a named CMMC
-- Level 2 practice with no partial credit, and it was the single largest gap in the control
-- catalogue: `enable_mfa`/`disable_mfa` existed in `keycloak_service.py` and were
-- unreachable — present, untested, called by nothing — and they would only ever have served
-- deployments running Keycloak, which is disabled by default.
--
-- WHY A SEPARATE TABLE RATHER THAN COLUMNS ON `users`. Three reasons, in order of weight:
--
--   * `users` is one of the tables NOT under row-level security (documented in
--     `app/api/user_management.py`: every query filters `organization_id` inline). Adding
--     secrets to it widens what an unscoped query can leak. This table is RLS-policied from
--     the moment it exists.
--   * Secrets and recovery codes want a different lifecycle from a profile row — revoke,
--     re-enrol, rotate — without UPDATEs on the row every request path reads.
--   * `SELECT * FROM users` appears in this codebase. A TOTP secret should not arrive in a
--     result set nobody asked to widen.
--
-- The secret is stored ENCRYPTED at the application layer, not in the clear: a database
-- backup or a read-only leak otherwise hands over the second factor, which would make it
-- theatre. See `app/core/mfa.py`.

CREATE TABLE IF NOT EXISTS user_mfa (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- AES-256-GCM envelope produced by app/core/mfa.py. Never the raw base32 secret.
    encrypted_secret TEXT NOT NULL,

    -- Enrolment is two-step: a secret is issued, and only a verified code activates it.
    -- Until then the user is NOT protected and must not be treated as if they were --
    -- an account that thinks it has MFA and does not is worse than one that knows it has none.
    confirmed_at TIMESTAMPTZ,

    -- Single-use recovery codes, stored as SHA-256 digests of high-entropy random values.
    -- Unsalted is correct here for the same reason it is for session tokens: these are
    -- 160-bit random strings, not passwords, so SP 800-132 does not apply.
    recovery_code_hashes JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- The last time window accepted, so a code cannot be replayed inside its own validity
    -- period. RFC 6238 section 5.2 requires exactly this and it is the step most
    -- implementations skip.
    last_used_window BIGINT,

    failed_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_mfa_user_id ON user_mfa(user_id);
CREATE INDEX IF NOT EXISTS idx_user_mfa_organization_id ON user_mfa(organization_id);

ALTER TABLE user_mfa ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_mfa FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_mfa_tenant_isolation ON user_mfa;
CREATE POLICY user_mfa_tenant_isolation ON user_mfa
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

COMMENT ON TABLE user_mfa IS
    'TOTP second factor for local accounts (800-171 3.5.3). One row per enrolled user; '
    'the secret is an AES-256-GCM envelope, never plaintext.';
