-- Migration: Create Kanban Task Management Tables
-- Description: Adds tables for the actionable decision-making kanban system

-- The `commands` table is created in 001_init.sql (which now includes
-- organization_id). The duplicate CREATE TABLE that previously lived
-- here was a no-op on a real database (001 runs first, so
-- CREATE TABLE IF NOT EXISTS was skipped) and left idx_commands_org
-- referencing a column that didn't exist. Indexes are kept below.

CREATE INDEX IF NOT EXISTS idx_commands_asset ON commands(asset_id);
CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(status);
CREATE INDEX IF NOT EXISTS idx_commands_org ON commands(organization_id);

-- Task Boards (unified board per organization)
CREATE TABLE IF NOT EXISTS task_boards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'Main Operations Board',
    board_type VARCHAR(50) DEFAULT 'unified', -- unified, production, maintenance, quality, safety, logistics
    default_view_config JSONB DEFAULT '{"default_filter": "all", "default_group_by": null, "show_wip_limits": true, "show_completed": false}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task Columns (kanban swimlanes)
CREATE TABLE IF NOT EXISTS task_columns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES task_boards(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    position INTEGER NOT NULL,
    wip_limit INTEGER DEFAULT 5,
    column_type VARCHAR(50) NOT NULL, -- backlog, triage, in_progress, review, rejected, done
    color VARCHAR(7) DEFAULT '#6366F1',
    is_collapsed BOOLEAN DEFAULT FALSE,
    auto_archive_days INTEGER DEFAULT 7,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tasks (central work items)
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES task_boards(id) ON DELETE CASCADE,
    column_id UUID NOT NULL REFERENCES task_columns(id) ON DELETE CASCADE,
    position INTEGER DEFAULT 0,
    
    -- Basic info
    title VARCHAR(500) NOT NULL,
    description TEXT,
    task_type VARCHAR(50) NOT NULL, -- production_job, maintenance_pm, maintenance_cm, quality_inspection, safety_check, alarm_response, command_execution, material_request, changeover, custom
    priority VARCHAR(20) DEFAULT 'medium', -- low, medium, high, critical, emergency
    status VARCHAR(50) DEFAULT 'draft', -- draft, ready, in_progress, blocked, completed, cancelled
    
    -- Assignments
    assigned_to UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_by UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ,
    
    -- Scheduling
    planned_start TIMESTAMPTZ,
    planned_duration INTEGER, -- minutes
    due_date TIMESTAMPTZ,
    actual_start TIMESTAMPTZ,
    actual_end TIMESTAMPTZ,
    
    -- Relationships to OmniusGrid entities
    asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    operation_id UUID REFERENCES operations(id) ON DELETE SET NULL,
    alarm_id UUID REFERENCES alarms(id) ON DELETE SET NULL,
    command_id VARCHAR(255),
    work_order_id UUID,
    parent_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    related_shipment_id UUID REFERENCES shipments(id) ON DELETE SET NULL,
    rule_id UUID, -- Will add FK after task_rules table created
    
    -- Progress tracking
    progress_percent INTEGER DEFAULT 0 CHECK (progress_percent >= 0 AND progress_percent <= 100),
    time_logged_minutes INTEGER DEFAULT 0,
    estimated_effort_minutes INTEGER,
    
    -- Metadata
    tags JSONB DEFAULT '[]'::jsonb,
    custom_fields JSONB DEFAULT '{}'::jsonb,
    checklist_items JSONB DEFAULT '[]'::jsonb,
    color_code VARCHAR(7),
    
    -- Approval workflow
    approval_status VARCHAR(50) DEFAULT 'pending', -- pending, approved, rejected
    approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ,
    rejection_reason TEXT,
    
    -- Completion actions (bidirectional integration)
    completion_actions JSONB DEFAULT '{}'::jsonb,
    completion_result JSONB DEFAULT '{}'::jsonb,
    
    -- Audit
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    completed_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Task Comments (activity feed)
CREATE TABLE IF NOT EXISTS task_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    comment_type VARCHAR(50) DEFAULT 'comment', -- comment, system, time_log, status_change, approval_action
    content TEXT,
    extra_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task Timers (time tracking)
CREATE TABLE IF NOT EXISTS task_timers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_minutes INTEGER DEFAULT 0,
    is_running BOOLEAN DEFAULT TRUE,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task Rules (automation rules registry)
CREATE TABLE IF NOT EXISTS task_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    rule_name VARCHAR(255) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_system_rule BOOLEAN DEFAULT FALSE, -- Premade vs custom
    
    -- Trigger conditions
    trigger_type VARCHAR(100) NOT NULL, -- alarm_created, alarm_cleared, packml_state_change, oee_threshold, telemetry_threshold, scheduled_time, operation_completed, command_failed, maintenance_due
    trigger_conditions JSONB DEFAULT '{}'::jsonb,
    
    -- Task template
    target_board_id UUID REFERENCES task_boards(id) ON DELETE SET NULL,
    target_column_id UUID REFERENCES task_columns(id) ON DELETE SET NULL,
    task_template JSONB DEFAULT '{}'::jsonb,
    
    -- Automation settings
    auto_approve_emergency BOOLEAN DEFAULT FALSE,
    auto_approve_timeout_minutes INTEGER DEFAULT 30,
    assignee_rule VARCHAR(50) DEFAULT 'asset_owner', -- round_robin, asset_owner, supervisor, specific_user
    specific_assignee_id UUID REFERENCES users(id) ON DELETE SET NULL,
    notify_users JSONB DEFAULT '[]'::jsonb,
    
    -- Completion actions
    completion_actions JSONB DEFAULT '{}'::jsonb,
    
    -- Escalation config
    escalation_config JSONB DEFAULT '{}'::jsonb,
    
    -- Audit
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add FK from tasks to task_rules (now that task_rules exists)
ALTER TABLE tasks 
ADD CONSTRAINT fk_task_rule 
FOREIGN KEY (rule_id) REFERENCES task_rules(id) ON DELETE SET NULL;

-- Task Escalations (escalation log)
CREATE TABLE IF NOT EXISTS task_escalations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    rule_id UUID REFERENCES task_rules(id) ON DELETE SET NULL,
    escalation_level INTEGER NOT NULL CHECK (escalation_level >= 1 AND escalation_level <= 5),
    triggered_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    notified_users JSONB DEFAULT '[]'::jsonb,
    actions_taken JSONB DEFAULT '[]'::jsonb,
    notification_channels JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_task_boards_org ON task_boards(organization_id);
CREATE INDEX IF NOT EXISTS idx_task_columns_board ON task_columns(board_id);
CREATE INDEX IF NOT EXISTS idx_task_columns_type ON task_columns(column_type);
CREATE INDEX IF NOT EXISTS idx_tasks_board ON tasks(board_id);
CREATE INDEX IF NOT EXISTS idx_tasks_column ON tasks(column_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tasks_asset ON tasks(asset_id);
CREATE INDEX IF NOT EXISTS idx_tasks_alarm ON tasks(alarm_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_approval ON tasks(approval_status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_completed_at ON tasks(completed_at);
CREATE INDEX IF NOT EXISTS idx_tasks_rule ON tasks(rule_id);
CREATE INDEX IF NOT EXISTS idx_task_comments_task ON task_comments(task_id);
CREATE INDEX IF NOT EXISTS idx_task_timers_task ON task_timers(task_id);
CREATE INDEX IF NOT EXISTS idx_task_timers_running ON task_timers(task_id, is_running);
CREATE INDEX IF NOT EXISTS idx_task_rules_org ON task_rules(organization_id);
CREATE INDEX IF NOT EXISTS idx_task_rules_trigger ON task_rules(trigger_type);
CREATE INDEX IF NOT EXISTS idx_task_escalations_task ON task_escalations(task_id);
CREATE INDEX IF NOT EXISTS idx_task_escalations_unresolved ON task_escalations(task_id, resolved_at) WHERE resolved_at IS NULL;

-- Update triggers for timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_task_boards_updated_at BEFORE UPDATE ON task_boards 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_task_columns_updated_at BEFORE UPDATE ON task_columns 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tasks_updated_at BEFORE UPDATE ON tasks 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_task_rules_updated_at BEFORE UPDATE ON task_rules 
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Comment on tables for documentation
COMMENT ON TABLE task_boards IS 'Unified kanban board configuration per organization';
COMMENT ON TABLE task_columns IS 'Kanban columns (Backlog, Triage, In Progress, Review, Rejected, Done)';
COMMENT ON TABLE tasks IS 'Central work items for actionable decision-making';
COMMENT ON TABLE task_comments IS 'Activity feed for tasks';
COMMENT ON TABLE task_timers IS 'Time tracking entries for tasks';
COMMENT ON TABLE task_rules IS 'Automation rules registry for auto-creating tasks';
COMMENT ON TABLE task_escalations IS 'Escalation log for overdue/unaddressed tasks';
