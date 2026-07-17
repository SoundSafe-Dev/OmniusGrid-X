-- Migration: Fix Kanban Task Management Tables
-- Description: Fixes foreign key constraints to work with existing schema

-- Drop existing kanban tables to recreate with correct constraints.
-- (tasks/task_comments/task_timers created by 003 must be dropped too, else the
--  CREATE TABLE below collides — initdb silently ignored this; the migration
--  runner does not, so 003's schema would otherwise win over this "fix".)
DROP TABLE IF EXISTS task_escalations CASCADE;
DROP TABLE IF EXISTS task_timers CASCADE;
DROP TABLE IF EXISTS task_comments CASCADE;
DROP TABLE IF EXISTS task_rules CASCADE;
DROP TABLE IF EXISTS tasks CASCADE;
DROP TABLE IF EXISTS task_columns CASCADE;
DROP TABLE IF EXISTS task_boards CASCADE;

-- Task Boards (unified board per organization)
CREATE TABLE task_boards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'Main Operations Board',
    board_type VARCHAR(50) DEFAULT 'unified',
    default_view_config JSONB DEFAULT '{"default_filter": "all", "default_group_by": null, "show_wip_limits": true, "show_completed": false}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task Columns (kanban swimlanes)
CREATE TABLE task_columns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES task_boards(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    position INTEGER NOT NULL,
    wip_limit INTEGER DEFAULT 5,
    column_type VARCHAR(50) NOT NULL,
    color VARCHAR(7) DEFAULT '#6366F1',
    is_collapsed BOOLEAN DEFAULT FALSE,
    auto_archive_days INTEGER DEFAULT 7,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tasks (central work items) - simplified without problematic FKs
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id UUID NOT NULL REFERENCES task_boards(id) ON DELETE CASCADE,
    column_id UUID NOT NULL REFERENCES task_columns(id) ON DELETE CASCADE,
    position INTEGER DEFAULT 0,
    
    -- Basic info
    title VARCHAR(500) NOT NULL,
    description TEXT,
    task_type VARCHAR(50) NOT NULL,
    priority VARCHAR(20) DEFAULT 'medium',
    status VARCHAR(50) DEFAULT 'draft',
    
    -- Assignments
    assigned_to UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_by UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMPTZ,
    
    -- Scheduling
    planned_start TIMESTAMPTZ,
    planned_duration INTEGER,
    due_date TIMESTAMPTZ,
    actual_start TIMESTAMPTZ,
    actual_end TIMESTAMPTZ,
    
    -- Relationships to OmniusGrid entities (no FKs to avoid schema issues)
    asset_id UUID,
    operation_id UUID,
    alarm_id UUID,
    command_id VARCHAR(255),
    work_order_id UUID,
    parent_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    rule_id UUID,
    
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
    approval_status VARCHAR(50) DEFAULT 'pending',
    approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ,
    rejection_reason TEXT,
    
    -- Completion actions
    completion_actions JSONB DEFAULT '{}'::jsonb,
    completion_result JSONB DEFAULT '{}'::jsonb,
    
    -- Audit
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    completed_by UUID REFERENCES users(id) ON DELETE SET NULL
);

-- Task Comments
CREATE TABLE task_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    comment_type VARCHAR(50) DEFAULT 'comment',
    content TEXT,
    extra_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Task Timers
CREATE TABLE task_timers (
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

-- Task Rules
CREATE TABLE task_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    rule_name VARCHAR(255) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_system_rule BOOLEAN DEFAULT FALSE,
    trigger_type VARCHAR(100) NOT NULL,
    trigger_conditions JSONB DEFAULT '{}'::jsonb,
    target_board_id UUID REFERENCES task_boards(id) ON DELETE SET NULL,
    target_column_id UUID REFERENCES task_columns(id) ON DELETE SET NULL,
    task_template JSONB DEFAULT '{}'::jsonb,
    auto_approve_emergency BOOLEAN DEFAULT FALSE,
    auto_approve_timeout_minutes INTEGER DEFAULT 30,
    assignee_rule VARCHAR(50) DEFAULT 'asset_owner',
    specific_assignee_id UUID REFERENCES users(id) ON DELETE SET NULL,
    notify_users JSONB DEFAULT '[]'::jsonb,
    completion_actions JSONB DEFAULT '{}'::jsonb,
    escalation_config JSONB DEFAULT '{}'::jsonb,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Add FK from tasks to task_rules
ALTER TABLE tasks 
ADD CONSTRAINT fk_task_rule 
FOREIGN KEY (rule_id) REFERENCES task_rules(id) ON DELETE SET NULL;

-- Task Escalations
CREATE TABLE task_escalations (
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

-- Indexes
CREATE INDEX idx_task_boards_org ON task_boards(organization_id);
CREATE INDEX idx_task_columns_board ON task_columns(board_id);
CREATE INDEX idx_task_columns_type ON task_columns(column_type);
CREATE INDEX idx_tasks_board ON tasks(board_id);
CREATE INDEX idx_tasks_column ON tasks(column_id);
CREATE INDEX idx_tasks_assignee ON tasks(assigned_to);
CREATE INDEX idx_tasks_asset ON tasks(asset_id);
CREATE INDEX idx_tasks_alarm ON tasks(alarm_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_priority ON tasks(priority);
CREATE INDEX idx_tasks_due_date ON tasks(due_date);
CREATE INDEX idx_tasks_approval ON tasks(approval_status);
CREATE INDEX idx_tasks_created_at ON tasks(created_at);
CREATE INDEX idx_tasks_completed_at ON tasks(completed_at);
CREATE INDEX idx_tasks_rule ON tasks(rule_id);
CREATE INDEX idx_task_comments_task ON task_comments(task_id);
CREATE INDEX idx_task_timers_task ON task_timers(task_id);
CREATE INDEX idx_task_timers_running ON task_timers(task_id, is_running);
CREATE INDEX idx_task_rules_org ON task_rules(organization_id);
CREATE INDEX idx_task_rules_trigger ON task_rules(trigger_type);
CREATE INDEX idx_task_escalations_task ON task_escalations(task_id);
CREATE INDEX idx_task_escalations_unresolved ON task_escalations(task_id, resolved_at) WHERE resolved_at IS NULL;

-- Update triggers
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
