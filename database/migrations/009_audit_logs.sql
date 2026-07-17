-- Migration 009: Security Audit Logging
-- Creates audit_logs table for tracking sensitive operations with SHA-256 hash chaining

-- Create audit_logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    organization_id UUID REFERENCES organizations(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id VARCHAR(36),  -- polymorphic: route names/config keys, not always a UUID
    details JSONB NOT NULL DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    hash_chain VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_organization_id ON audit_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_hash_chain ON audit_logs(hash_chain);

-- Create composite index for filtering
CREATE INDEX IF NOT EXISTS idx_audit_logs_org_timestamp ON audit_logs(organization_id, timestamp DESC);

-- Add comment to table
COMMENT ON TABLE audit_logs IS 'Security audit log for tracking sensitive operations with tamper-evident hash chaining';

-- Add comments to columns
COMMENT ON COLUMN audit_logs.action IS 'Action performed: user_created, user_deleted, asset_updated, command_executed, etc.';
COMMENT ON COLUMN audit_logs.resource_type IS 'Type of resource affected: user, asset, command, registry_item, kanban_task';
COMMENT ON COLUMN audit_logs.resource_id IS 'ID of the affected resource';
COMMENT ON COLUMN audit_logs.details IS 'JSONB details including before/after state, parameters, etc.';
COMMENT ON COLUMN audit_logs.hash_chain IS 'SHA-256 hash of previous hash + current log data for tamper detection';

-- Create function to calculate hash chain
CREATE OR REPLACE FUNCTION calculate_audit_hash(
    p_previous_hash VARCHAR,
    p_log_data JSONB
) RETURNS VARCHAR AS $$
DECLARE
    combined TEXT;
BEGIN
    combined := COALESCE(p_previous_hash, '') || jsonb_pretty(p_log_data);
    RETURN encode(digest(combined::bytea, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql;

-- Create trigger for automatic hash chain calculation
CREATE OR REPLACE FUNCTION audit_log_hash_chain_trigger()
RETURNS TRIGGER AS $$
DECLARE
    previous_hash VARCHAR;
BEGIN
    -- Get the hash of the most recent log entry
    SELECT hash_chain INTO previous_hash
    FROM audit_logs
    WHERE id IS NOT NULL
    ORDER BY timestamp DESC, id DESC
    LIMIT 1;
    
    -- Calculate new hash chain
    NEW.hash_chain = calculate_audit_hash(previous_hash, to_jsonb(NEW));
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger on audit_logs table
DROP TRIGGER IF EXISTS audit_log_hash_chain_trigger ON audit_logs;
CREATE TRIGGER audit_log_hash_chain_trigger
    BEFORE INSERT ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_hash_chain_trigger();

-- Grant permissions (adjust based on your security model)
DO $$
BEGIN
    -- omniusgrid_app is an optional least-privilege role some deployments
    -- create; the default deployments run as the omniusgrid superuser role.
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'omniusgrid_app') THEN
        GRANT SELECT, INSERT ON audit_logs TO omniusgrid_app;
    END IF;
END $$;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'omniusgrid_readonly') THEN
        GRANT SELECT ON audit_logs TO omniusgrid_readonly;
    END IF;
END $$;

-- Create view for audit log summary
CREATE OR REPLACE VIEW audit_log_summary AS
SELECT 
    id,
    timestamp,
    user_id,
    organization_id,
    action,
    resource_type,
    resource_id,
    ip_address,
    hash_chain
FROM audit_logs
ORDER BY timestamp DESC;

COMMENT ON VIEW audit_log_summary IS 'Simplified view of audit logs without sensitive details';
