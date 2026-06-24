-- ERP Integration Tables
-- Migration 019: revived from ERP WIP commit 527e14a5 and adapted to the
-- current tenant/RLS convention (`app.current_org_id`).

ALTER TABLE integration_configurations
ADD COLUMN IF NOT EXISTS erp_type VARCHAR(50),
ADD COLUMN IF NOT EXISTS erp_version VARCHAR(50),
ADD COLUMN IF NOT EXISTS sync_schedule VARCHAR(100),
ADD COLUMN IF NOT EXISTS last_successful_sync TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS sync_frequency_minutes INTEGER DEFAULT 60;

CREATE INDEX IF NOT EXISTS idx_integration_erp_type
  ON integration_configurations(erp_type)
  WHERE erp_type IS NOT NULL;

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
    processing_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_erp_events UNIQUE(source_system, event_id),
    CONSTRAINT ck_erp_events_status CHECK (
      processing_status IN ('pending', 'processing', 'completed', 'failed', 'retrying')
    )
);

CREATE INDEX IF NOT EXISTS idx_erp_events_org ON erp_integration_events(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_events_integration ON erp_integration_events(integration_id);
CREATE INDEX IF NOT EXISTS idx_erp_events_status ON erp_integration_events(processing_status);
CREATE INDEX IF NOT EXISTS idx_erp_events_created ON erp_integration_events(created_at DESC);

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
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_erp_mappings UNIQUE(integration_id, source_entity, source_field)
);

CREATE INDEX IF NOT EXISTS idx_erp_mappings_org ON erp_data_mappings(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_mappings_integration ON erp_data_mappings(integration_id);

CREATE TABLE IF NOT EXISTS erp_sync_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    integration_id UUID NOT NULL REFERENCES integration_configurations(id) ON DELETE CASCADE,
    entity_type VARCHAR(100) NOT NULL,
    last_sync_at TIMESTAMPTZ,
    last_sync_status VARCHAR(50),
    records_synced INTEGER NOT NULL DEFAULT 0,
    records_failed INTEGER NOT NULL DEFAULT 0,
    sync_duration_seconds NUMERIC,
    next_sync_at TIMESTAMPTZ,
    delta_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_erp_sync UNIQUE(integration_id, entity_type),
    CONSTRAINT ck_erp_sync_status CHECK (
      last_sync_status IS NULL
      OR last_sync_status IN ('queued', 'running', 'success', 'failed', 'partial')
    )
);

CREATE INDEX IF NOT EXISTS idx_erp_sync_org ON erp_sync_status(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_sync_integration ON erp_sync_status(integration_id);

CREATE TABLE IF NOT EXISTS erp_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    integration_id UUID NOT NULL REFERENCES integration_configurations(id) ON DELETE CASCADE,
    entity_type VARCHAR(100) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    entity_data JSONB NOT NULL,
    source_system VARCHAR(50) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_erp_entities UNIQUE(integration_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_erp_entities_org ON erp_entities(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_entities_integration ON erp_entities(integration_id);
CREATE INDEX IF NOT EXISTS idx_erp_entities_type ON erp_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_erp_entities_active
  ON erp_entities(is_active)
  WHERE is_active = TRUE;

CREATE TABLE IF NOT EXISTS erp_correlations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    correlation_type VARCHAR(100) NOT NULL,
    erp_event_id UUID REFERENCES erp_integration_events(id) ON DELETE SET NULL,
    sensor_event_id UUID,
    correlation_score NUMERIC,
    correlation_metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_erp_correlations_org ON erp_correlations(organization_id);
CREATE INDEX IF NOT EXISTS idx_erp_correlations_type ON erp_correlations(correlation_type);

ALTER TABLE erp_integration_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_integration_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON erp_integration_events;
CREATE POLICY tenant_isolation ON erp_integration_events
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE erp_data_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_data_mappings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON erp_data_mappings;
CREATE POLICY tenant_isolation ON erp_data_mappings
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE erp_sync_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_sync_status FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON erp_sync_status;
CREATE POLICY tenant_isolation ON erp_sync_status
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE erp_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_entities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON erp_entities;
CREATE POLICY tenant_isolation ON erp_entities
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE erp_correlations ENABLE ROW LEVEL SECURITY;
ALTER TABLE erp_correlations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON erp_correlations;
CREATE POLICY tenant_isolation ON erp_correlations
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
