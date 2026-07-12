-- Migration: Create Actionable Registries and Data Correlation Tables
-- Description: Adds tables for actionable registries (compliance and operational) and data correlation mapping

-- Actionable Registries table
CREATE TABLE IF NOT EXISTS actionable_registries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    registry_name VARCHAR(255) NOT NULL,
    registry_type VARCHAR(50) NOT NULL,
    registry_category VARCHAR(100),
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_compliance BOOLEAN DEFAULT FALSE,
    frequency VARCHAR(50),
    next_due_date TIMESTAMPTZ,
    last_completed_date TIMESTAMPTZ,
    compliance_score INTEGER DEFAULT 0,
    priority_level VARCHAR(20) DEFAULT 'medium',
    assigned_owner_id UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_team_id UUID,
    reference_url VARCHAR(500),
    checklist_requirements JSONB DEFAULT '[]'::jsonb,
    meta_data JSONB DEFAULT '{}'::jsonb,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Actionable Registry Items table
CREATE TABLE IF NOT EXISTS actionable_registry_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    registry_id UUID NOT NULL REFERENCES actionable_registries(id) ON DELETE CASCADE,
    item_code VARCHAR(100) NOT NULL,
    item_name VARCHAR(255) NOT NULL,
    item_description TEXT,
    severity_level VARCHAR(20) DEFAULT 'medium',
    is_active BOOLEAN DEFAULT TRUE,
    is_required BOOLEAN DEFAULT TRUE,
    completion_criteria TEXT,
    verification_method VARCHAR(255),
    estimated_effort_minutes INTEGER,
    related_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    last_completed_at TIMESTAMPTZ,
    next_due_at TIMESTAMPTZ,
    completion_frequency VARCHAR(50),
    compliance_score INTEGER DEFAULT 0,
    risk_score INTEGER DEFAULT 0,
    meta_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Data Correlations table
CREATE TABLE IF NOT EXISTS data_correlations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    correlation_type VARCHAR(50) NOT NULL,
    source_type VARCHAR(50) NOT NULL,
    source_id UUID,
    target_type VARCHAR(50) NOT NULL,
    target_id UUID,
    correlation_strength INTEGER DEFAULT 50,
    correlation_method VARCHAR(50) DEFAULT 'manual',
    confidence_score INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    is_bidirectional BOOLEAN DEFAULT FALSE,
    correlation_meta_data JSONB DEFAULT '{}'::jsonb,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for actionable_registries
CREATE INDEX IF NOT EXISTS idx_actionable_registries_org ON actionable_registries(organization_id);
CREATE INDEX IF NOT EXISTS idx_actionable_registries_type ON actionable_registries(registry_type);
CREATE INDEX IF NOT EXISTS idx_actionable_registries_compliance ON actionable_registries(is_compliance);
CREATE INDEX IF NOT EXISTS idx_actionable_registries_active ON actionable_registries(is_active);
CREATE INDEX IF NOT EXISTS idx_actionable_registries_due ON actionable_registries(next_due_date);
CREATE INDEX IF NOT EXISTS idx_actionable_registries_owner ON actionable_registries(assigned_owner_id);

-- Indexes for actionable_registry_items
CREATE INDEX IF NOT EXISTS idx_actionable_registry_items_registry ON actionable_registry_items(registry_id);
CREATE INDEX IF NOT EXISTS idx_actionable_registry_items_task ON actionable_registry_items(related_task_id);
CREATE INDEX IF NOT EXISTS idx_actionable_registry_items_severity ON actionable_registry_items(severity_level);
CREATE INDEX IF NOT EXISTS idx_actionable_registry_items_active ON actionable_registry_items(is_active);
CREATE INDEX IF NOT EXISTS idx_actionable_registry_items_due ON actionable_registry_items(next_due_at);
CREATE INDEX IF NOT EXISTS idx_actionable_registry_items_risk ON actionable_registry_items(risk_score);

-- Indexes for data_correlations
CREATE INDEX IF NOT EXISTS idx_data_correlations_org ON data_correlations(organization_id);
CREATE INDEX IF NOT EXISTS idx_data_correlations_type ON data_correlations(correlation_type);
CREATE INDEX IF NOT EXISTS idx_data_correlations_source ON data_correlations(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_data_correlations_target ON data_correlations(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_data_correlations_strength ON data_correlations(correlation_strength);
CREATE INDEX IF NOT EXISTS idx_data_correlations_active ON data_correlations(is_active);

-- Update trigger for updated_at
DROP TRIGGER IF EXISTS update_actionable_registries_updated_at ON actionable_registries;
CREATE TRIGGER update_actionable_registries_updated_at BEFORE UPDATE ON actionable_registries 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_actionable_registry_items_updated_at ON actionable_registry_items;
CREATE TRIGGER update_actionable_registry_items_updated_at BEFORE UPDATE ON actionable_registry_items 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_data_correlations_updated_at ON data_correlations;
CREATE TRIGGER update_data_correlations_updated_at BEFORE UPDATE ON data_correlations 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Comments for documentation
COMMENT ON TABLE actionable_registries IS 'Actionable registries for compliance and operational requirements';
COMMENT ON TABLE actionable_registry_items IS 'Individual actionable items within a registry';
COMMENT ON TABLE data_correlations IS 'Data correlation mapping for tasks and actionable items';
