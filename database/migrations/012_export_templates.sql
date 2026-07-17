-- Task 5: saved export templates, schedules, and durable delivery outbox.

CREATE TABLE IF NOT EXISTS export_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    export_type VARCHAR(50) NOT NULL,
    export_format VARCHAR(10) NOT NULL,
    columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_export_templates_org_name UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_export_templates_org
    ON export_templates(organization_id);

CREATE TABLE IF NOT EXISTS scheduled_exports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    template_id UUID NOT NULL REFERENCES export_templates(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    frequency VARCHAR(20) NOT NULL CHECK (frequency IN ('daily', 'weekly', 'monthly')),
    timezone VARCHAR(100) NOT NULL DEFAULT 'UTC',
    next_run_at TIMESTAMPTZ NOT NULL,
    recipients JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    last_run_at TIMESTAMPTZ,
    last_status VARCHAR(50) DEFAULT 'never_run',
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scheduled_exports_org
    ON scheduled_exports(organization_id);
CREATE INDEX IF NOT EXISTS idx_scheduled_exports_due
    ON scheduled_exports(next_run_at)
    WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS export_delivery_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    schedule_id UUID NOT NULL REFERENCES scheduled_exports(id) ON DELETE CASCADE,
    template_id UUID NOT NULL REFERENCES export_templates(id) ON DELETE CASCADE,
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    scheduled_for TIMESTAMPTZ NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    file_path TEXT,
    filename VARCHAR(255),
    error TEXT,
    published_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_export_delivery_jobs_schedule_run
        UNIQUE (schedule_id, scheduled_for)
);

CREATE INDEX IF NOT EXISTS idx_export_delivery_jobs_status
    ON export_delivery_jobs(status, created_at);

ALTER TABLE export_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE export_templates FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON export_templates;
CREATE POLICY tenant_isolation ON export_templates
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE scheduled_exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE scheduled_exports FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON scheduled_exports;
CREATE POLICY tenant_isolation ON scheduled_exports
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE export_delivery_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE export_delivery_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON export_delivery_jobs;
CREATE POLICY tenant_isolation ON export_delivery_jobs
    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
