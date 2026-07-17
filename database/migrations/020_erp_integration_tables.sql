-- ERP Integration Tables
-- Migration 011: Add ERP integration support

-- ERP Integration Events
CREATE TABLE IF NOT EXISTS erp_integration_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    integration_id UUID NOT NULL REFERENCES integration_configurations(id) ON DELETE CASCADE,
    event_type VARCHAR(100) NOT NULL,
    event_id VARCHAR(255) NOT NULL,
    source_system VARCHAR(50) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id VARCHAR(255),
    event_data JSONB NOT NULL,
    processed_at TIMESTAMPTZ,
    processing_status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_erp_events UNIQUE(source_system, event_id)
);

CREATE INDEX IF NOT EXISTS idx_erp_events_org ON erp_integration_events(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_events_integration ON erp_integration_events(integration_id);
CREATE INDEX IF NOT EXISTS idx_erp_events_status ON erp_integration_events(processing_status);
CREATE INDEX IF NOT EXISTS idx_erp_events_created ON erp_integration_events(created_at DESC);

-- ERP Data Mappings
CREATE TABLE IF NOT EXISTS erp_data_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    integration_id UUID NOT NULL REFERENCES integration_configurations(id) ON DELETE CASCADE,
    source_entity VARCHAR(100) NOT NULL,
    source_field VARCHAR(100) NOT NULL,
    target_entity VARCHAR(100) NOT NULL,
    target_field VARCHAR(100) NOT NULL,
    transformation_rule TEXT,
    data_type VARCHAR(50),
    is_required BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_erp_mappings UNIQUE(integration_id, source_entity, source_field)
);

CREATE INDEX IF NOT EXISTS idx_erp_mappings_org ON erp_data_mappings(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_mappings_integration ON erp_data_mappings(integration_id);

-- ERP Sync Status
CREATE TABLE IF NOT EXISTS erp_sync_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    integration_id UUID NOT NULL REFERENCES integration_configurations(id) ON DELETE CASCADE,
    entity_type VARCHAR(100) NOT NULL,
    last_sync_at TIMESTAMPTZ,
    last_sync_status VARCHAR(50),
    records_synced INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    sync_duration_seconds NUMERIC,
    next_sync_at TIMESTAMPTZ,
    delta_token TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_erp_sync UNIQUE(integration_id, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_erp_sync_org ON erp_sync_status(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_sync_integration ON erp_sync_status(integration_id);

-- ERP Entities (Normalized Data)
CREATE TABLE IF NOT EXISTS erp_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    integration_id UUID NOT NULL REFERENCES integration_configurations(id) ON DELETE CASCADE,
    entity_type VARCHAR(100) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    entity_data JSONB NOT NULL,
    source_system VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    valid_from TIMESTAMPTZ DEFAULT NOW(),
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_erp_entities UNIQUE(integration_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_erp_entities_org ON erp_entities(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_entities_integration ON erp_entities(integration_id);
CREATE INDEX IF NOT EXISTS idx_erp_entities_type ON erp_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_erp_entities_active ON erp_entities(is_active) WHERE is_active = TRUE;

-- ERP Correlations
CREATE TABLE IF NOT EXISTS erp_correlations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    correlation_type VARCHAR(100) NOT NULL,
    erp_event_id UUID REFERENCES erp_integration_events(id),
    sensor_event_id UUID,
    correlation_score FLOAT,
    correlation_metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_erp_correlations_org ON erp_correlations(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_correlations_type ON erp_correlations(correlation_type);

-- Add ERP-specific columns to integration_configurations table
ALTER TABLE integration_configurations 
ADD COLUMN IF NOT EXISTS erp_type VARCHAR(50),
ADD COLUMN IF NOT EXISTS erp_version VARCHAR(50),
ADD COLUMN IF NOT EXISTS sync_schedule VARCHAR(100),
ADD COLUMN IF NOT EXISTS last_successful_sync TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS sync_frequency_minutes INTEGER DEFAULT 60;

-- Create index on erp_type
CREATE INDEX IF NOT EXISTS idx_integration_erp_type ON integration_configurations(erp_type) WHERE erp_type IS NOT NULL;

-- Row-level security policies for multi-tenant isolation
-- FS-56: these policies originally said TO authenticated_users (a role that
-- never existed anywhere — the file could not apply) and keyed on the
-- app.current_organization_id GUC (which nothing sets; the canonical GUC is
-- app.current_org_id, see 011). Rewritten to the codebase convention so ERP
-- tenant isolation actually enforces.
DO $$
BEGIN
  IF to_regclass('public.erp_integration_events') IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='erp_integration_events'
      AND column_name='organization_id' AND data_type='character varying'
  ) THEN
    ALTER TABLE erp_integration_events ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS erp_events_org_isolation ON erp_integration_events;
    CREATE POLICY erp_events_org_isolation ON erp_integration_events
        FOR ALL
        USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

DO $$
BEGIN
  IF to_regclass('public.erp_data_mappings') IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='erp_data_mappings'
      AND column_name='organization_id' AND data_type='character varying'
  ) THEN
    ALTER TABLE erp_data_mappings ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS erp_mappings_org_isolation ON erp_data_mappings;
    CREATE POLICY erp_mappings_org_isolation ON erp_data_mappings
        FOR ALL
        USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

DO $$
BEGIN
  IF to_regclass('public.erp_sync_status') IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='erp_sync_status'
      AND column_name='organization_id' AND data_type='character varying'
  ) THEN
    ALTER TABLE erp_sync_status ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS erp_sync_org_isolation ON erp_sync_status;
    CREATE POLICY erp_sync_org_isolation ON erp_sync_status
        FOR ALL
        USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

DO $$
BEGIN
  IF to_regclass('public.erp_entities') IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='erp_entities'
      AND column_name='organization_id' AND data_type='character varying'
  ) THEN
    ALTER TABLE erp_entities ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS erp_entities_org_isolation ON erp_entities;
    CREATE POLICY erp_entities_org_isolation ON erp_entities
        FOR ALL
        USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

DO $$
BEGIN
  IF to_regclass('public.erp_correlations') IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='erp_correlations'
      AND column_name='organization_id' AND data_type='character varying'
  ) THEN
    ALTER TABLE erp_correlations ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS erp_correlations_org_isolation ON erp_correlations;
    CREATE POLICY erp_correlations_org_isolation ON erp_correlations
        FOR ALL
        USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- Grant permissions
DO $$
BEGIN
    -- optional least-privilege role; default deployments run as omniusgrid
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opsgrid_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON erp_integration_events TO opsgrid_user;
    END IF;
END $$;
DO $$
BEGIN
    -- optional least-privilege role; default deployments run as omniusgrid
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opsgrid_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON erp_data_mappings TO opsgrid_user;
    END IF;
END $$;
DO $$
BEGIN
    -- optional least-privilege role; default deployments run as omniusgrid
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opsgrid_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON erp_sync_status TO opsgrid_user;
    END IF;
END $$;
DO $$
BEGIN
    -- optional least-privilege role; default deployments run as omniusgrid
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opsgrid_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON erp_entities TO opsgrid_user;
    END IF;
END $$;
DO $$
BEGIN
    -- optional least-privilege role; default deployments run as omniusgrid
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'opsgrid_user') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON erp_correlations TO opsgrid_user;
    END IF;
END $$;
