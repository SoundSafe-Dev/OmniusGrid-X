-- Populate Kanban board with extended test data covering YMS, TMS, and other systems

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
    v_rejected_col_id UUID;
BEGIN
    -- Get existing board for dev organization
    SELECT id INTO v_board_id FROM task_boards WHERE organization_id = v_dev_org_id AND is_active = TRUE LIMIT 1;

    -- Dev sample data only: skip on a clean database (no dev board yet).
    IF v_board_id IS NULL THEN
        RAISE NOTICE 'no dev board found; skipping extended kanban sample data';
        RETURN;
    END IF;
    
    -- Get column IDs
    SELECT id INTO v_backlog_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'backlog' LIMIT 1;
    SELECT id INTO v_triage_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'triage' LIMIT 1;
    SELECT id INTO v_in_progress_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'in_progress' LIMIT 1;
    SELECT id INTO v_review_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'review' LIMIT 1;
    SELECT id INTO v_done_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'done' LIMIT 1;
    SELECT id INTO v_rejected_col_id FROM task_columns WHERE board_id = v_board_id AND column_type = 'rejected' LIMIT 1;
    
    -- YMS (Yard Management System) Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_backlog_col_id, 5, 'Schedule yard truck for inbound container #4521', 'Container arrival at gate 3, needs yard truck assignment for unloading area', 'custom', 'high', 'ready', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_backlog_col_id, 6, 'Optimize yard slot allocation for Zone B', 'Current slot utilization at 85%, need rebalancing', 'custom', 'medium', 'draft', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_triage_col_id, 3, 'Investigate yard gate scanner malfunction', 'Gate 4 RFID scanner not reading 20% of tags, needs troubleshooting', 'alarm_response', 'critical', 'ready', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- TMS (Transportation Management System) Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_backlog_col_id, 7, 'Route optimization for delivery fleet #2', 'Current routes showing 15% inefficiency, need recalculation', 'custom', 'medium', 'ready', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_backlog_col_id, 8, 'Schedule carrier pickup for Order #7890', 'Customer awaiting pickup, need carrier assignment', 'custom', 'high', 'ready', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_in_progress_col_id, 3, 'Track shipment #SHIP-2024-1234 ETA', 'Shipment delayed at port, need updated ETA calculation', 'custom', 'high', 'in_progress', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- Logistics Correlation Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_backlog_col_id, 9, 'Correlate inventory levels with production schedule', 'Inventory mismatch detected between WMS and ERP', 'custom', 'high', 'draft', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_in_progress_col_id, 4, 'Analyze logistics bottleneck in shipping dock', 'Shipping dock throughput down 30%, investigate root cause', 'custom', 'critical', 'in_progress', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- More Production Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by, progress_percent)
    VALUES 
        (v_board_id, v_backlog_col_id, 10, 'Setup production run for Product C - Batch #5000', 'New product line setup required', 'production_job', 'high', 'ready', v_dev_user_id, v_dev_user_id, 0),
        (v_board_id, v_in_progress_col_id, 5, 'Monitor quality metrics for Line 2', 'Real-time quality monitoring during production shift', 'quality_inspection', 'medium', 'in_progress', v_dev_user_id, v_dev_user_id, 65)
    ON CONFLICT DO NOTHING;
    
    -- More Maintenance Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_backlog_col_id, 11, 'Schedule conveyor belt replacement', 'Conveyor belt #3 showing wear, plan replacement during downtime', 'maintenance_pm', 'medium', 'draft', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_triage_col_id, 4, 'Emergency repair: Hydraulic pump failure', 'Main hydraulic pump failed, immediate repair required', 'maintenance_cm', 'emergency', 'ready', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- More Safety Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_backlog_col_id, 12, 'Conduct monthly safety audit for Zone A', 'Required monthly safety inspection', 'safety_check', 'high', 'ready', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_review_col_id, 3, 'Review incident report #INC-2024-0042', 'Minor injury incident needs investigation and corrective action', 'safety_check', 'high', 'ready', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- More Alarm Response Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_triage_col_id, 5, 'Investigate low pressure warning in pneumatic system', 'Pressure dropped below threshold in Line 1', 'alarm_response', 'high', 'ready', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_done_col_id, 4, 'Respond to temperature spike in oven #2', 'Temperature exceeded limit, cooling system activated and resolved', 'alarm_response', 'critical', 'completed', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- More Command Execution Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_backlog_col_id, 13, 'Execute emergency stop sequence test', 'Monthly emergency stop sequence verification', 'command_execution', 'high', 'draft', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_review_col_id, 4, 'Verify command execution log for batch processing', 'Review automated command logs for compliance', 'command_execution', 'medium', 'ready', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- More Material Request Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by)
    VALUES 
        (v_board_id, v_backlog_col_id, 14, 'Order raw materials for Q3 production', 'Need to place bulk order for steel and plastic components', 'material_request', 'high', 'ready', v_dev_user_id, v_dev_user_id),
        (v_board_id, v_done_col_id, 5, 'Restock packaging supplies', 'Packaging materials replenished', 'material_request', 'medium', 'completed', v_dev_user_id, v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- More Changeover Tasks
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by, progress_percent)
    VALUES 
        (v_board_id, v_backlog_col_id, 15, 'Plan changeover for Line 4 - Product X to Y', 'Changeover scheduled for weekend shift', 'changeover', 'high', 'ready', v_dev_user_id, v_dev_user_id, 0),
        (v_board_id, v_done_col_id, 6, 'Complete mold change on injection machine #2', 'Mold change completed successfully', 'changeover', 'medium', 'completed', v_dev_user_id, v_dev_user_id, 100)
    ON CONFLICT DO NOTHING;
    
    -- Add more tasks to Done column
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by, completed_at, completed_by)
    VALUES 
        (v_board_id, v_done_col_id, 7, 'Yard slot rebalancing completed', 'Zone B rebalanced, utilization now at 72%', 'custom', 'medium', 'completed', v_dev_user_id, v_dev_user_id, NOW() - INTERVAL '2 hours', v_dev_user_id),
        (v_board_id, v_done_col_id, 8, 'Carrier assigned to Order #7889', 'Carrier confirmed, pickup scheduled', 'custom', 'high', 'completed', v_dev_user_id, v_dev_user_id, NOW() - INTERVAL '4 hours', v_dev_user_id)
    ON CONFLICT DO NOTHING;
    
    -- Add tasks to Review column
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by, approval_status)
    VALUES 
        (v_board_id, v_review_col_id, 5, 'Approve overtime request for maintenance team', 'Maintenance team requesting 8 hours overtime for emergency repairs', 'custom', 'high', 'ready', v_dev_user_id, v_dev_user_id, 'pending'),
        (v_board_id, v_review_col_id, 6, 'Review and approve new safety protocol draft', 'Updated safety procedures for confined spaces', 'safety_check', 'high', 'ready', v_dev_user_id, v_dev_user_id, 'pending')
    ON CONFLICT DO NOTHING;
    
    -- Add more tasks to Rejected column
    INSERT INTO tasks (board_id, column_id, position, title, description, task_type, priority, status, assigned_to, created_by, approval_status, rejection_reason)
    VALUES 
        (v_board_id, v_rejected_col_id, 2, 'Changeover request rejected - insufficient time', 'Changeover request denied due to production schedule conflict', 'changeover', 'high', 'completed', v_dev_user_id, v_dev_user_id, 'rejected', 'Production schedule conflict'),
        (v_board_id, v_rejected_col_id, 3, 'Material request rejected - budget exceeded', 'Bulk order rejected due to Q2 budget constraints', 'material_request', 'medium', 'completed', v_dev_user_id, v_dev_user_id, 'rejected', 'Budget exceeded')
    ON CONFLICT DO NOTHING;
    
    RAISE NOTICE 'Extended kanban test data populated successfully';
END $$;
