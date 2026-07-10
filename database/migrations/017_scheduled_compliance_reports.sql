-- =============================================================================
-- Migration 017: Scheduled compliance reports (durable schedules + job linkage)
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS scheduled_compliance_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name VARCHAR(255) NOT NULL,
    framework VARCHAR(20) NOT NULL,
    format VARCHAR(10) NOT NULL,
    frequency VARCHAR(20) NOT NULL,
    timezone VARCHAR(100) NOT NULL DEFAULT 'UTC',
    next_run_at TIMESTAMPTZ NOT NULL,
    recipients JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    last_run_at TIMESTAMPTZ,
    last_status VARCHAR(50) NOT NULL DEFAULT 'never_run',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_scheduled_compliance_reports_framework
        CHECK (framework IN ('all', 'gdpr', 'soc2', 'iso27001')),
    CONSTRAINT ck_scheduled_compliance_reports_format
        CHECK (format IN ('json', 'pdf')),
    CONSTRAINT ck_scheduled_compliance_reports_frequency
        CHECK (frequency IN ('daily', 'weekly', 'monthly', 'quarterly', 'annually')),
    CONSTRAINT fk_scheduled_compliance_reports_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_scheduled_compliance_reports_created_by
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

ALTER TABLE scheduled_compliance_reports
    ALTER COLUMN recipients TYPE JSONB USING recipients::jsonb,
    ALTER COLUMN recipients SET DEFAULT '[]'::jsonb,
    ALTER COLUMN timezone SET DEFAULT 'UTC',
    ALTER COLUMN is_active SET DEFAULT FALSE,
    ALTER COLUMN last_status SET DEFAULT 'never_run',
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE scheduled_compliance_reports
    DROP CONSTRAINT IF EXISTS ck_scheduled_compliance_reports_framework,
    DROP CONSTRAINT IF EXISTS ck_scheduled_compliance_reports_format,
    DROP CONSTRAINT IF EXISTS ck_scheduled_compliance_reports_frequency;

ALTER TABLE scheduled_compliance_reports
    ADD CONSTRAINT ck_scheduled_compliance_reports_framework
        CHECK (framework IN ('all', 'gdpr', 'soc2', 'iso27001')),
    ADD CONSTRAINT ck_scheduled_compliance_reports_format
        CHECK (format IN ('json', 'pdf')),
    ADD CONSTRAINT ck_scheduled_compliance_reports_frequency
        CHECK (frequency IN ('daily', 'weekly', 'monthly', 'quarterly', 'annually'));

CREATE INDEX IF NOT EXISTS idx_scheduled_compliance_reports_org
    ON scheduled_compliance_reports(organization_id);

CREATE INDEX IF NOT EXISTS idx_scheduled_compliance_reports_due
    ON scheduled_compliance_reports(next_run_at)
    WHERE is_active = TRUE;

ALTER TABLE scheduled_compliance_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE scheduled_compliance_reports FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON scheduled_compliance_reports;
CREATE POLICY tenant_isolation ON scheduled_compliance_reports
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

ALTER TABLE compliance_report_jobs
    ADD COLUMN IF NOT EXISTS schedule_id UUID,
    ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ;

DO $$
DECLARE
    fk_name TEXT;
BEGIN
    FOR fk_name IN
        SELECT tc.constraint_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON kcu.constraint_schema = tc.constraint_schema
         AND kcu.constraint_name = tc.constraint_name
         AND kcu.table_schema = tc.table_schema
         AND kcu.table_name = tc.table_name
        WHERE tc.constraint_schema = current_schema()
          AND tc.table_name = 'compliance_report_jobs'
          AND tc.constraint_type = 'FOREIGN KEY'
          AND kcu.column_name = 'schedule_id'
    LOOP
        EXECUTE format(
            'ALTER TABLE compliance_report_jobs DROP CONSTRAINT %I',
            fk_name
        );
    END LOOP;
END
$$;

ALTER TABLE compliance_report_jobs
    ADD CONSTRAINT fk_compliance_report_jobs_schedule
        FOREIGN KEY (schedule_id)
        REFERENCES scheduled_compliance_reports(id)
        ON DELETE SET NULL;

ALTER TABLE compliance_report_jobs
    DROP CONSTRAINT IF EXISTS uq_compliance_report_jobs_schedule_run;

ALTER TABLE compliance_report_jobs
    ADD CONSTRAINT uq_compliance_report_jobs_schedule_run
        UNIQUE (schedule_id, scheduled_for);

COMMIT;
