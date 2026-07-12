-- Populate Kanban board with test data for dev organization

-- Get dev organization and user IDs (hardcoded from auth.py)
DO $$
DECLARE
    v_dev_org_id UUID := '00000000-0000-0000-0000-000000000001'::UUID;
    v_dev_user_id UUID := '00000000-0000-0000-0000-000000000001'::UUID;
    v_board_id UUID;
    v_backlog_col_id UUID;
    v_triage_col_id UUID;
    v_in_progress_col_id UUID;
    v_review_col_id UUID;
    v_done_col_id UUID;
BEGIN
    -- Get existing board for dev organization (don't create new one)
    SELECT id INTO v_board_id FROM task_boards WHERE organization_id = v_dev_org_id AND is_active = TRUE LIMIT 1;

    -- Dev sample data only: on a clean database there is no dev board yet
    -- (the app creates it at first login) — skip instead of violating
    -- task_columns.board_id NOT NULL.
    IF v_board_id IS NULL THEN
        RAISE NOTICE 'no dev board found; skipping kanban sample data';
        RETURN;
    END IF;

    -- Create columns
    INSERT INTO task_columns (board_id, name, position, wip_limit, column_type, color)
    VALUES 
        (v_board_id, 'Backlog', 1, 10, 'backlog', '#6B7280'),
        (v_board_id, 'Triage', 2, 5, 'triage', '#F59E0B'),
        (v_board_id, 'In Progress', 3, 5, 'in_progress', '#3B82F6'),
        (v_board_id, 'Review', 4, 3, 'review', '#8B5CF6'),
        (v_board_id, 'Done', 5, 999, 'done', '#10B981')
    ON CONFLICT DO NOTHING;
    
    -- Get column IDs
    SELECT id INTO v_backlog_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'backlog' LIMIT 1;
    SELECT id INTO v_triage_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'triage' LIMIT 1;
    SELECT id INTO v_in_progress_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'in_progress' LIMIT 1;
    SELECT id INTO v_review_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'review' LIMIT 1;
    SELECT id INTO v_done_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'done' LIMIT 1;
    
    -- Create sample tasks in Backlog
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_backlog_col_id, 1, 'Schedule preventive maintenance for 3D Printer #1', 'Monthly calibration and cleaning scheduled for production line 3D printer', 'maintenance_pm', 'medium', 'ready', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_backlog_col_id, 2, 'Review quality inspection results for Batch #4521', 'Quality metrics show 2% defect rate, needs root cause analysis', 'quality_inspection', 'high', 'ready', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_backlog_col_id, 3, 'Update safety protocols for CNC machines', 'New OSHA guidelines require updated lockout/tagout procedures', 'safety_check', 'critical', 'draft', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_backlog_col_id, 4, 'Material request: Filament spools for Q3', 'Need 50 spools of PLA filament for upcoming production run', 'material_request', 'low', 'ready', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- Create sample tasks in Triage
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_triage_col_id, 1, 'Investigate alarm: High temperature on extruder', 'Temperature sensor reading 15°C above threshold, investigate cooling system', 'alarm_response', 'critical', 'ready', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_triage_col_id, 2, 'Execute command: Emergency stop on conveyor belt', 'Safety interlock triggered, need to verify motor status before restart', 'command_execution', 'high', 'in_progress', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- Create sample tasks in In Progress
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by, actual_start)
    VALUES 
        (v_board_id, v_in_progress_col_id, 1, 'Changeover from Product A to Product B', 'Production line changeover in progress, currently at step 3 of 5', 'changeover', 'medium', 'in_progress', v_dev_user_id, v_dev_user_id, NOW() - INTERVAL '2 hours'),
        (v_board_id, v_in_progress_col_id, 2, 'Calibration of vision system', 'Camera calibration for quality inspection system', 'maintenance_cm', 'high', 'in_progress', v_dev_user_id, v_dev_user_id, NOW() - INTERVAL '4 hours')
    ON CONFLICT DO NOTHING;
    
    -- Create sample tasks in Review
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by, approval_status)
    VALUES 
        (v_board_id, v_review_col_id, 1, 'Complete firmware update on PLC #3', 'Firmware update completed, awaiting final sign-off', 'maintenance_cm', 'high', 'blocked', v_dev_user_id, v_dev_user_id, 'pending'),
        (v_board_id, v_review_col_id, 2, 'Approve work order #1234 for production run', 'Production work order ready for supervisor approval', 'production_job', 'medium', 'ready', v_dev_user_id, v_dev_user_id, 'approved')
    ON CONFLICT DO NOTHING;
    
    -- Create sample tasks in Done
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by, completed_at, completed_by)
    VALUES 
        (v_board_id, v_done_col_id, 1, 'Clean dust collection filters', 'Routine maintenance completed successfully', 'maintenance_pm', 'low', 'completed', v_dev_user_id, v_dev_user_id, NOW() - INTERVAL '1 day', v_dev_user_id),
        (v_board_id, v_done_col_id, 2, 'Respond to low ink warning on labeling printer', 'Replaced ink cartridge and verified print quality', 'alarm_response', 'medium', 'completed', v_dev_user_id, v_dev_user_id, NOW() - INTERVAL '3 hours', v_dev_user_id),
        (v_board_id, v_done_col_id, 3, 'Update inventory database', 'Weekly inventory sync completed', 'custom', 'low', 'completed', v_dev_user_id, v_dev_user_id, NOW() - INTERVAL '5 hours', v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    RAISE NOTICE 'Test kanban data populated successfully';
END $$;
