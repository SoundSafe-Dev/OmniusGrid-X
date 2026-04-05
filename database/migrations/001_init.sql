-- OmniusGrid Database Schema
-- TimescaleDB with PackML state machine support

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Organizations (multi-tenancy)
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    settings JSONB DEFAULT '{}'
);

-- Workcells (logical grouping of assets)
CREATE TABLE workcells (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    location VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Asset Types (equipment categories with PackML config)
CREATE TABLE asset_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    category VARCHAR(100) NOT NULL, -- '3d_printer', 'cnc', 'robot', etc.
    packml_config JSONB NOT NULL DEFAULT '{}',
    -- Example: {"state_mappings": {"printing": "Execute", "heating": "Starting"}}
    telemetry_schema JSONB NOT NULL DEFAULT '{}',
    -- Example: {"fields": [{"name": "temp_nozzle", "type": "float", "unit": "°C"}]}
    action_space JSONB DEFAULT '{}',
    -- Example: {"actions": [{"id": "set_speed", "type": "continuous", "range": [50, 150]}]}
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Assets (individual equipment instances)
CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workcell_id UUID REFERENCES workcells(id) ON DELETE SET NULL,
    asset_type_id UUID NOT NULL REFERENCES asset_types(id),
    name VARCHAR(255) NOT NULL,
    serial_number VARCHAR(255),
    vendor VARCHAR(100),
    model VARCHAR(100),
    current_packml_state VARCHAR(50) DEFAULT 'Idle',
    connection_config JSONB NOT NULL DEFAULT '{}',
    -- Example: {"protocol": "mqtt", "host": "192.168.1.100", "port": 8883}
    is_active BOOLEAN DEFAULT TRUE,
    last_seen TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- PackML State History (for OEE calculations)
CREATE TABLE packml_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    state VARCHAR(50) NOT NULL, -- PackML state: Idle, Starting, Execute, Held, Suspended, etc.
    previous_state VARCHAR(50),
    state_entered_at TIMESTAMPTZ NOT NULL,
    state_exited_at TIMESTAMPTZ,
    duration_seconds NUMERIC,
    metadata JSONB DEFAULT '{}',
    -- Example: {"reason": "material_change", "operator_id": "uuid"}
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('packml_states', 'state_entered_at', if_not_exists => TRUE);

-- Telemetry (time-series sensor readings)
CREATE TABLE telemetry (
    time TIMESTAMPTZ NOT NULL,
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    metric_name VARCHAR(100) NOT NULL,
    value NUMERIC NOT NULL,
    unit VARCHAR(50),
    packml_state VARCHAR(50), -- Denormalized for faster queries
    metadata JSONB DEFAULT '{}',
    sequence_num BIGINT -- For ordering and deduplication
);

-- Convert to hypertable
SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);

-- Compression policy: compress after 7 days
SELECT add_compression_policy('telemetry', INTERVAL '7 days', if_not_exists => TRUE);

-- Retention policy: drop raw data after 30 days (aggregates kept longer)
SELECT add_retention_policy('telemetry', INTERVAL '30 days', if_not_exists => TRUE);

-- Enable compression on telemetry
ALTER TABLE telemetry SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id, metric_name'
);

-- Telemetry 1-minute aggregates (cold tier / long-term retention)
CREATE MATERIALIZED VIEW telemetry_1min (
    time, asset_id, metric_name, avg_value, min_value, max_value, sample_count
)
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    asset_id,
    metric_name,
    avg(value) AS avg_value,
    min(value) AS min_value,
    max(value) AS max_value,
    count(*) AS sample_count
FROM telemetry
GROUP BY bucket, asset_id, metric_name;

-- Create index on continuous aggregate
CREATE INDEX idx_telemetry_1min_asset_metric ON telemetry_1min (asset_id, metric_name, time DESC);

-- Operations (jobs/processes)
CREATE TABLE operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    operation_name VARCHAR(255) NOT NULL,
    job_id VARCHAR(255),
    status VARCHAR(50) NOT NULL, -- 'running', 'completed', 'failed', 'cancelled'
    packml_state_durations JSONB DEFAULT '{}',
    -- Example: {"Execute": 3600, "Starting": 120, "Idle": 0}
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    planned_duration INTEGER, -- seconds
    actual_duration INTEGER, -- seconds
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Alarms (ISA-18.2 compliant)
CREATE TABLE alarms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    alarm_code VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    message TEXT NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by UUID,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_comment TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    cleared_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

SELECT create_hypertable('alarms', 'occurred_at', if_not_exists => TRUE);

-- Commands (operator and engine-issued actions)
CREATE TABLE commands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    command_type VARCHAR(100) NOT NULL, -- 'operator', 'engine', 'system'
    action_id VARCHAR(100) NOT NULL, -- matches action_space definition
    parameters JSONB NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- 'pending', 'executing', 'completed', 'failed'
    issued_by UUID,
    issued_at TIMESTAMPTZ DEFAULT NOW(),
    executed_at TIMESTAMPTZ,
    result JSONB,
    digital_signature VARCHAR(255), -- for engine commands
    verified BOOLEAN DEFAULT FALSE,
    audit_log TEXT
);

-- Telemetry Buffers (edge agent tracking)
CREATE TABLE telemetry_buffers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    agent_id VARCHAR(255) NOT NULL,
    buffer_path VARCHAR(500) NOT NULL,
    records_count INTEGER DEFAULT 0,
    oldest_record_at TIMESTAMPTZ,
    newest_record_at TIMESTAMPTZ,
    is_connected BOOLEAN DEFAULT TRUE,
    last_sync_at TIMESTAMPTZ,
    backfill_status VARCHAR(50) DEFAULT 'idle', -- 'idle', 'in_progress', 'complete', 'error'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Reward metrics for game-theoretic engine
CREATE TABLE reward_metrics (
    time TIMESTAMPTZ NOT NULL,
    asset_id UUID REFERENCES assets(id) ON DELETE CASCADE,
    operation_id UUID REFERENCES operations(id),
    energy_consumption_kwh DOUBLE PRECISION,
    time_efficiency_score DOUBLE PRECISION,
    waste_percentage DOUBLE PRECISION,
    quality_score DOUBLE PRECISION,
    overall_reward DOUBLE PRECISION,
    metadata JSONB,
    FOREIGN KEY (asset_id) REFERENCES assets(id)
);

SELECT create_hypertable('reward_metrics', 'time', chunk_time_interval => INTERVAL '1 day');

-- Users and authentication
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    organization_id UUID REFERENCES organizations(id),
    role VARCHAR(50) NOT NULL DEFAULT 'operator',
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_login TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Device identity and certificate management (Zero-Trust)
CREATE TABLE device_identities (
    device_id VARCHAR(255) PRIMARY KEY,
    asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    device_type VARCHAR(100) NOT NULL,
    certificate_pem TEXT NOT NULL,
    private_key_pem TEXT,  -- Only stored during initial provisioning
    fingerprint VARCHAR(64) UNIQUE NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, approved, suspended, revoked
    approved_by VARCHAR(255),
    approved_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_reason TEXT,
    last_seen TIMESTAMPTZ,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create index for fingerprint lookups
CREATE INDEX idx_device_identities_fingerprint ON device_identities(fingerprint);
CREATE INDEX idx_device_identities_status ON device_identities(status);

-- Immutable audit trail for compliance
CREATE TABLE audit_trail (
    entry_id VARCHAR(64) PRIMARY KEY,  -- SHA256 hash
    timestamp TIMESTAMPTZ NOT NULL,
    actor_type VARCHAR(20) NOT NULL,  -- human, ai_tactical, ai_strategic, system, api
    actor_id VARCHAR(255) NOT NULL,
    command_type VARCHAR(50) NOT NULL,
    asset_id UUID NOT NULL REFERENCES assets(id),
    previous_state JSONB NOT NULL,
    new_state JSONB NOT NULL,
    command_parameters JSONB NOT NULL,
    execution_result VARCHAR(20) NOT NULL,  -- success, failed, blocked
    execution_error TEXT,
    ip_address INET,
    session_id VARCHAR(255),
    hash_chain VARCHAR(64),  -- Link to previous entry
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for audit trail queries
CREATE INDEX idx_audit_trail_timestamp ON audit_trail(timestamp);
CREATE INDEX idx_audit_trail_asset_id ON audit_trail(asset_id);
CREATE INDEX idx_audit_trail_actor_id ON audit_trail(actor_id);
CREATE INDEX idx_audit_trail_command_type ON audit_trail(command_type);

-- Partition audit trail by time for performance
SELECT create_hypertable('audit_trail', 'timestamp', chunk_time_interval => INTERVAL '1 day');

-- Enable compression for audit trail (older data less frequently accessed)
ALTER TABLE audit_trail SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'asset_id'
);

-- Indexes for performance
CREATE INDEX idx_assets_org ON assets(organization_id);
CREATE INDEX idx_assets_workcell ON assets(workcell_id);
CREATE INDEX idx_assets_type ON assets(asset_type_id);
CREATE INDEX idx_packml_states_asset ON packml_states(asset_id, state_entered_at DESC);
CREATE INDEX idx_telemetry_asset_time ON telemetry(asset_id, time DESC);
CREATE INDEX idx_telemetry_metric ON telemetry(asset_id, metric_name, time DESC);
CREATE INDEX idx_alarms_asset ON alarms(asset_id, occurred_at DESC);
CREATE INDEX idx_alarms_active ON alarms(is_active, severity);
CREATE INDEX idx_operations_asset ON operations(asset_id, started_at DESC);

-- Function to calculate OEE for an asset and time range
CREATE OR REPLACE FUNCTION calculate_oee(
    p_asset_id UUID,
    p_start_time TIMESTAMPTZ,
    p_end_time TIMESTAMPTZ
) RETURNS TABLE (
    availability NUMERIC,
    performance NUMERIC,
    quality NUMERIC,
    oee NUMERIC
) AS $$
DECLARE
    total_time NUMERIC;
    execute_time NUMERIC;
    planned_production_time NUMERIC;
    ideal_cycle_time NUMERIC;
    actual_output NUMERIC;
    good_output NUMERIC;
BEGIN
    -- Calculate availability (Execute time / Planned production time)
    SELECT COALESCE(SUM(duration_seconds), 0)
    INTO execute_time
    FROM packml_states
    WHERE asset_id = p_asset_id
      AND state = 'Execute'
      AND state_entered_at >= p_start_time
      AND state_entered_at < p_end_time;
    
    total_time := EXTRACT(EPOCH FROM (p_end_time - p_start_time));
    planned_production_time := total_time; -- Adjust for breaks if needed
    
    availability := CASE 
        WHEN planned_production_time > 0 
        THEN execute_time / planned_production_time 
        ELSE 0 
    END;
    
    -- Performance and Quality would need additional production data
    -- Placeholder calculations
    performance := 1.0; -- Would calculate based on actual vs ideal cycle time
    quality := 1.0; -- Would calculate based on good parts / total parts
    oee := availability * performance * quality;
    
    RETURN QUERY SELECT availability, performance, quality, oee;
END;
$$ LANGUAGE plpgsql;

-- Insert default asset types
INSERT INTO asset_types (name, category, packml_config, telemetry_schema) VALUES
('FDM 3D Printer', '3d_printer', 
 '{"state_mappings": {"printing": "Execute", "heating": "Starting", "idle": "Idle", "paused": "Held", "error": "Aborted"}}',
 '{"fields": [{"name": "temp_nozzle", "type": "float", "unit": "°C"}, {"name": "temp_bed", "type": "float", "unit": "°C"}, {"name": "progress", "type": "float", "unit": "%"}, {"name": "print_speed", "type": "float", "unit": "mm/s"}]}'),

('CNC Mill', 'cnc',
 '{"state_mappings": {"running": "Execute", "spindle_warmup": "Starting", "tool_change": "Held", "alarm": "Aborted"}}',
 '{"fields": [{"name": "spindle_rpm", "type": "float", "unit": "rpm"}, {"name": "feed_rate", "type": "float", "unit": "mm/min"}, {"name": "tool_number", "type": "integer"}]}'),

('Robotic Arm', 'robot',
 '{"state_mappings": {"moving": "Execute", "homing": "Starting", "waiting": "Idle", "e_stopped": "Aborted"}}',
 '{"fields": [{"name": "joint_1_pos", "type": "float", "unit": "deg"}, {"name": "tcp_x", "type": "float", "unit": "mm"}, {"name": "tcp_speed", "type": "float", "unit": "mm/s"}]}');

-- Insert default organization for development
INSERT INTO organizations (name, slug) VALUES 
('Development Organization', 'dev-org')
ON CONFLICT (slug) DO NOTHING;
