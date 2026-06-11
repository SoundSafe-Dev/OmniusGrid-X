-- =============================================================================
-- Migration 016: Finalize compliance tenant ownership
-- =============================================================================
--
-- Run only after the manual review documented in:
-- docs/deployment/runbooks/compliance-tenant-data-cleanup.md
--
-- This migration deliberately aborts if migration 014 left any unresolved rows.
-- It never guesses ownership and never deletes legacy data automatically.
-- =============================================================================

BEGIN;

DO $$
DECLARE
    unresolved_assets BIGINT;
    unresolved_assessments BIGINT;
BEGIN
    SELECT count(*) INTO unresolved_assets
    FROM security_assets
    WHERE organization_id IS NULL;

    SELECT count(*) INTO unresolved_assessments
    FROM vendor_risk_assessments
    WHERE organization_id IS NULL;

    IF unresolved_assets > 0 OR unresolved_assessments > 0 THEN
        RAISE EXCEPTION
            'Cannot enforce compliance tenant ownership: % security_assets and % vendor_risk_assessments still have NULL organization_id. Complete the manual review before retrying migration 016.',
            unresolved_assets,
            unresolved_assessments;
    END IF;
END $$;

ALTER TABLE security_assets
    ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE vendor_risk_assessments
    ALTER COLUMN organization_id SET NOT NULL;

COMMENT ON COLUMN security_assets.organization_id IS
    'Owning organization. Required and enforced by tenant RLS.';

COMMENT ON COLUMN vendor_risk_assessments.organization_id IS
    'Owning organization. Required and enforced by tenant RLS.';

COMMIT;
