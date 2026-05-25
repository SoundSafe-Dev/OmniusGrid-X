-- API Keys table for external integrations
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash VARCHAR(64) NOT NULL UNIQUE,  -- SHA-256 hash of the API key
    key_prefix VARCHAR(8) NOT NULL,  -- First 8 chars for identification
    name VARCHAR(255) NOT NULL,
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    scopes TEXT[] NOT NULL DEFAULT ARRAY['read'],  -- read, write, admin
    is_active BOOLEAN NOT NULL DEFAULT true,
    expires_at TIMESTAMP WITH TIME ZONE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by UUID REFERENCES users(id),
    revoked_at TIMESTAMP WITH TIME ZONE,
    revoked_by UUID REFERENCES users(id),
    metadata JSONB DEFAULT '{}'
);

-- Indexes
CREATE INDEX idx_api_keys_organization ON api_keys(organization_id);
CREATE INDEX idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_key_prefix ON api_keys(key_prefix);
CREATE INDEX idx_api_keys_is_active ON api_keys(is_active) WHERE is_active = true;

-- Permissions table for RBAC
CREATE TABLE IF NOT EXISTS permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    resource VARCHAR(50) NOT NULL,  -- assets, alarms, telemetry, kanban, etc.
    action VARCHAR(50) NOT NULL,  -- create, read, update, delete, admin
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert default permissions
INSERT INTO permissions (name, description, resource, action) VALUES
('assets.create', 'Create assets', 'assets', 'create'),
('assets.read', 'View assets', 'assets', 'read'),
('assets.update', 'Update assets', 'assets', 'update'),
('assets.delete', 'Delete assets', 'assets', 'delete'),
('alarms.create', 'Create alarms', 'alarms', 'create'),
('alarms.read', 'View alarms', 'alarms', 'read'),
('alarms.update', 'Update alarms', 'alarms', 'update'),
('alarms.delete', 'Delete alarms', 'alarms', 'delete'),
('telemetry.read', 'View telemetry', 'telemetry', 'read'),
('telemetry.write', 'Write telemetry', 'telemetry', 'write'),
('kanban.create', 'Create kanban tasks', 'kanban', 'create'),
('kanban.read', 'View kanban tasks', 'kanban', 'read'),
('kanban.update', 'Update kanban tasks', 'kanban', 'update'),
('kanban.delete', 'Delete kanban tasks', 'kanban', 'delete'),
('kanban.admin', 'Admin kanban boards', 'kanban', 'admin'),
('users.create', 'Create users', 'users', 'create'),
('users.read', 'View users', 'users', 'read'),
('users.update', 'Update users', 'users', 'update'),
('users.delete', 'Delete users', 'users', 'delete'),
('users.admin', 'Admin user management', 'users', 'admin'),
('registries.create', 'Create registries', 'registries', 'create'),
('registries.read', 'View registries', 'registries', 'read'),
('registries.update', 'Update registries', 'registries', 'update'),
('registries.delete', 'Delete registries', 'registries', 'delete'),
('system.admin', 'System administration', 'system', 'admin'),
('audit.read', 'View audit logs', 'audit', 'read'),
('commands.execute', 'Execute commands', 'commands', 'execute'),
('commands.admin', 'Admin commands', 'commands', 'admin');

-- Role permissions mapping table
CREATE TABLE IF NOT EXISTS role_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role VARCHAR(50) NOT NULL,  -- admin, operator, viewer
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(role, permission_id)
);

-- Insert default role permissions
-- Admin: All permissions
INSERT INTO role_permissions (role, permission_id)
SELECT 'admin', id FROM permissions;

-- Operator: Read/write for operational data, no system config
INSERT INTO role_permissions (role, permission_id)
SELECT 'operator', id FROM permissions 
WHERE name IN (
    'assets.read', 'assets.update',
    'alarms.read', 'alarms.update',
    'telemetry.read', 'telemetry.write',
    'kanban.create', 'kanban.read', 'kanban.update',
    'registries.read', 'registries.update',
    'audit.read',
    'commands.execute'
);

-- Viewer: Read-only access
INSERT INTO role_permissions (role, permission_id)
SELECT 'viewer', id FROM permissions 
WHERE name LIKE '%.read';

-- User sessions table
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_activity_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    revoked_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'
);

-- Indexes for sessions
CREATE INDEX idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_token_hash ON user_sessions(token_hash);
CREATE INDEX idx_user_sessions_is_active ON user_sessions(is_active) WHERE is_active = true;
CREATE INDEX idx_user_sessions_expires_at ON user_sessions(expires_at);

-- Consent records for GDPR
CREATE TABLE IF NOT EXISTS consent_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    consent_type VARCHAR(50) NOT NULL,  -- data_processing, marketing, analytics
    consent_given BOOLEAN NOT NULL,
    consent_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    consent_method VARCHAR(50),  -- checkbox, signature, electronic
    ip_address VARCHAR(45),
    user_agent TEXT,
    withdrawn_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_consent_records_user ON consent_records(user_id);
CREATE INDEX idx_consent_records_type ON consent_records(consent_type);

-- Data processing records for GDPR
CREATE TABLE IF NOT EXISTS data_processing_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    processing_activity VARCHAR(255) NOT NULL,
    data_categories TEXT[] NOT NULL,
    purposes TEXT[] NOT NULL,
    recipients TEXT[],
    retention_period VARCHAR(100),
    security_measures TEXT[],
    legal_basis VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_data_processing_org ON data_processing_records(organization_id);

-- Assets table for ISO 27001
CREATE TABLE IF NOT EXISTS security_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_type VARCHAR(50) NOT NULL,  -- hardware, software, data, service
    asset_name VARCHAR(255) NOT NULL,
    asset_id VARCHAR(255),
    owner_id UUID REFERENCES users(id),
    classification VARCHAR(50),  -- public, internal, confidential, restricted
    location VARCHAR(255),
    status VARCHAR(50) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_security_assets_type ON security_assets(asset_type);
CREATE INDEX idx_security_assets_owner ON security_assets(owner_id);

-- Vendor risk assessments for SOC 2
CREATE TABLE IF NOT EXISTS vendor_risk_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vendor_name VARCHAR(255) NOT NULL,
    vendor_type VARCHAR(50),
    risk_level VARCHAR(50),  -- low, medium, high, critical
    assessment_date DATE,
    next_review_date DATE,
    assessor_id UUID REFERENCES users(id),
    findings TEXT[],
    controls TEXT[],
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_vendor_risk_vendor ON vendor_risk_assessments(vendor_name);
CREATE INDEX idx_vendor_risk_level ON vendor_risk_assessments(risk_level);

-- Integration configurations
CREATE TABLE IF NOT EXISTS integration_configurations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_type VARCHAR(50) NOT NULL,  -- erp, mes, wms, iot
    integration_name VARCHAR(255) NOT NULL,
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    configuration JSONB NOT NULL,
    authentication JSONB,
    is_active BOOLEAN NOT NULL DEFAULT true,
    health_check_url VARCHAR(500),
    last_health_check TIMESTAMP WITH TIME ZONE,
    health_status VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by UUID REFERENCES users(id)
);

CREATE INDEX idx_integration_config_type ON integration_configurations(integration_type);
CREATE INDEX idx_integration_config_org ON integration_configurations(organization_id);
CREATE INDEX idx_integration_config_active ON integration_configurations(is_active) WHERE is_active = true;

-- Data residency tags
CREATE TABLE IF NOT EXISTS data_residency_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name VARCHAR(100) NOT NULL,
    record_id UUID NOT NULL,
    region VARCHAR(50) NOT NULL DEFAULT 'USA',
    tagged_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    tagged_by UUID REFERENCES users(id),
    metadata JSONB DEFAULT '{}',
    UNIQUE(table_name, record_id)
);

CREATE INDEX idx_data_residency_table ON data_residency_tags(table_name);
CREATE INDEX idx_data_residency_region ON data_residency_tags(region);
