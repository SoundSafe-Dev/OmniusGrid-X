-- =============================================================================
-- Migration 014: Compliance tenant isolation (security_assets, vendor_risk_assessments)
-- =============================================================================
--
-- Adds nullable organization_id columns temporarily, backfills from owner/assessor
-- users where possible, and enables strict RLS (fail-closed for NULL rows).
--
-- NULL organization_id is TEMPORARY: legacy rows without resolvable ownership
-- remain in the table but are intentionally invisible and non-writable through
-- tenant-scoped sessions. A follow-up migration must resolve all NULL values
-- and apply migration 016 before deploying ORM fields as non-nullable.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- security_assets
-- -----------------------------------------------------------------------------

ALTER TABLE security_assets
    ADD COLUMN IF NOT EXISTS organization_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'security_assets_organization_id_fkey'
          AND conrelid = 'security_assets'::regclass
    ) THEN
        ALTER TABLE security_assets
            ADD CONSTRAINT security_assets_organization_id_fkey
            FOREIGN KEY (organization_id)
            REFERENCES organizations(id)
            ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_security_assets_organization_id
    ON security_assets(organization_id);

COMMENT ON COLUMN security_assets.organization_id IS
    'Temporary nullable tenant ownership. NULL legacy rows are inaccessible via RLS until migration 016 enforces NOT NULL after manual review.';

UPDATE security_assets
SET organization_id = users.organization_id
FROM users
WHERE security_assets.owner_id = users.id
  AND security_assets.organization_id IS NULL
  AND users.organization_id IS NOT NULL;

DO $$
DECLARE
    unresolved_assets INTEGER;
BEGIN
    SELECT count(*) INTO unresolved_assets
    FROM security_assets
    WHERE organization_id IS NULL;

    RAISE NOTICE 'security_assets with unresolved organization_id: %', unresolved_assets;
END $$;

ALTER TABLE security_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE security_assets FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON security_assets;
CREATE POLICY tenant_isolation ON security_assets
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

-- -----------------------------------------------------------------------------
-- vendor_risk_assessments
-- -----------------------------------------------------------------------------

ALTER TABLE vendor_risk_assessments
    ADD COLUMN IF NOT EXISTS organization_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'vendor_risk_assessments_organization_id_fkey'
          AND conrelid = 'vendor_risk_assessments'::regclass
    ) THEN
        ALTER TABLE vendor_risk_assessments
            ADD CONSTRAINT vendor_risk_assessments_organization_id_fkey
            FOREIGN KEY (organization_id)
            REFERENCES organizations(id)
            ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_vendor_risk_assessments_organization_id
    ON vendor_risk_assessments(organization_id);

COMMENT ON COLUMN vendor_risk_assessments.organization_id IS
    'Temporary nullable tenant ownership. NULL legacy rows are inaccessible via RLS until migration 016 enforces NOT NULL after manual review.';

UPDATE vendor_risk_assessments
SET organization_id = users.organization_id
FROM users
WHERE vendor_risk_assessments.assessor_id = users.id
  AND vendor_risk_assessments.organization_id IS NULL
  AND users.organization_id IS NOT NULL;

DO $$
DECLARE
    unresolved_assessments INTEGER;
BEGIN
    SELECT count(*) INTO unresolved_assessments
    FROM vendor_risk_assessments
    WHERE organization_id IS NULL;

    RAISE NOTICE 'vendor_risk_assessments with unresolved organization_id: %', unresolved_assessments;
END $$;

ALTER TABLE vendor_risk_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_risk_assessments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON vendor_risk_assessments;
CREATE POLICY tenant_isolation ON vendor_risk_assessments
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

COMMIT;
