-- =============================================================================
-- Migration 015: Compliance report async jobs (durable outbox + strict RLS)
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS compliance_report_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    requested_by UUID,
    framework VARCHAR(20) NOT NULL,
    format VARCHAR(10) NOT NULL,
    recipients JSONB NOT NULL DEFAULT '[]'::jsonb,
    report_status VARCHAR(20) NOT NULL DEFAULT 'queued',
    delivery_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    publication_attempts INTEGER NOT NULL DEFAULT 0,
    generation_attempts INTEGER NOT NULL DEFAULT 0,
    email_attempts INTEGER NOT NULL DEFAULT 0,
    error_report TEXT,
    error_delivery TEXT,
    file_path TEXT,
    filename VARCHAR(255),
    media_type VARCHAR(100),
    file_size BIGINT,
    file_sha256 VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    email_sent_at TIMESTAMPTZ,
    CONSTRAINT ck_compliance_report_jobs_framework
        CHECK (framework IN ('all', 'gdpr', 'soc2', 'iso27001')),
    CONSTRAINT ck_compliance_report_jobs_format
        CHECK (format IN ('json', 'pdf')),
    CONSTRAINT ck_compliance_report_jobs_report_status
        CHECK (report_status IN (
            'queued', 'publishing', 'published', 'running', 'completed', 'failed'
        )),
    CONSTRAINT ck_compliance_report_jobs_delivery_status
        CHECK (delivery_status IN (
            'pending', 'sending', 'sent', 'failed', 'skipped'
        )),
    CONSTRAINT fk_compliance_report_jobs_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_compliance_report_jobs_requested_by
        FOREIGN KEY (requested_by) REFERENCES users(id) ON DELETE SET NULL
);

-- `init_db()` may have created this table from ORM metadata before migrations run.
-- Reconcile the type, defaults, checks, and FK actions so both bootstrap paths
-- produce the same schema.
ALTER TABLE compliance_report_jobs
    ALTER COLUMN recipients TYPE JSONB USING recipients::jsonb,
    ALTER COLUMN recipients SET DEFAULT '[]'::jsonb,
    ALTER COLUMN report_status SET DEFAULT 'queued',
    ALTER COLUMN delivery_status SET DEFAULT 'pending',
    ALTER COLUMN publication_attempts SET DEFAULT 0,
    ALTER COLUMN generation_attempts SET DEFAULT 0,
    ALTER COLUMN email_attempts SET DEFAULT 0,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE compliance_report_jobs
    DROP CONSTRAINT IF EXISTS ck_compliance_report_jobs_framework,
    DROP CONSTRAINT IF EXISTS ck_compliance_report_jobs_format,
    DROP CONSTRAINT IF EXISTS ck_compliance_report_jobs_report_status,
    DROP CONSTRAINT IF EXISTS ck_compliance_report_jobs_delivery_status;

ALTER TABLE compliance_report_jobs
    ADD CONSTRAINT ck_compliance_report_jobs_framework
        CHECK (framework IN ('all', 'gdpr', 'soc2', 'iso27001')),
    ADD CONSTRAINT ck_compliance_report_jobs_format
        CHECK (format IN ('json', 'pdf')),
    ADD CONSTRAINT ck_compliance_report_jobs_report_status
        CHECK (report_status IN (
            'queued', 'publishing', 'published', 'running', 'completed', 'failed'
        )),
    ADD CONSTRAINT ck_compliance_report_jobs_delivery_status
        CHECK (delivery_status IN (
            'pending', 'sending', 'sent', 'failed', 'skipped'
        ));

DO $$
DECLARE
    fk_name TEXT;
BEGIN
    FOR fk_name IN
        SELECT constraint_name
        FROM information_schema.key_column_usage
        WHERE table_schema = current_schema()
          AND table_name = 'compliance_report_jobs'
          AND column_name IN ('organization_id', 'requested_by')
          AND position_in_unique_constraint IS NOT NULL
    LOOP
        EXECUTE format(
            'ALTER TABLE compliance_report_jobs DROP CONSTRAINT %I',
            fk_name
        );
    END LOOP;
END
$$;

ALTER TABLE compliance_report_jobs
    ADD CONSTRAINT fk_compliance_report_jobs_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_compliance_report_jobs_requested_by
        FOREIGN KEY (requested_by) REFERENCES users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_compliance_report_jobs_org_created
    ON compliance_report_jobs(organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_compliance_report_jobs_report_status
    ON compliance_report_jobs(report_status);

CREATE INDEX IF NOT EXISTS idx_compliance_report_jobs_delivery_status
    ON compliance_report_jobs(delivery_status);

ALTER TABLE compliance_report_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_report_jobs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON compliance_report_jobs;
CREATE POLICY tenant_isolation ON compliance_report_jobs
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
