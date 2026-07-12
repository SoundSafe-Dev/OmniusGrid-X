-- Populate Actionable Registries with sample data

-- Get dev organization and user IDs (hardcoded from auth.py)
DO $$
DECLARE
    v_dev_org_id UUID := '00000000-0000-0000-0000-000000000001'::UUID;
    v_dev_user_id UUID := '00000000-0000-0000-0000-000000000001'::UUID;
    v_osha_registry_id UUID;
    v_iso_registry_id UUID;
    v_internal_safety_id UUID;
    v_internal_quality_id UUID;
    v_internal_ops_id UUID;
BEGIN
    -- Dev sample data only: requires the dev organization (created by the app
    -- at first boot). Skip on a clean database instead of violating the org FK.
    IF NOT EXISTS (SELECT 1 FROM organizations WHERE id = v_dev_org_id) THEN
        RAISE NOTICE 'dev organization missing; skipping registry sample data';
        RETURN;
    END IF;
    -- Create Compliance Registries (OSHA, ISO)
    
    -- OSHA 1910.147 - Lockout/Tagout
    INSERT INTO actionable_registries (
        id, organization_id, registry_name, registry_type, registry_category, description,
        is_compliance, frequency, next_due_date, compliance_score, priority_level,
        assigned_owner_id, reference_url, meta_data, created_by
    )
    VALUES (
        gen_random_uuid(), v_dev_org_id, 'OSHA 1910.147 - Lockout/Tagout', 'safety', 'machine_safety',
        'Control of hazardous energy sources during maintenance and servicing',
        TRUE, 'quarterly', NOW() + INTERVAL '30 days', 85, 'high',
        v_dev_user_id, 'https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.147', '{}'::jsonb, v_dev_user_id
    )
    RETURNING id INTO v_osha_registry_id;
    
    -- ISO 9001:2015 - Quality Management
    INSERT INTO actionable_registries (
        id, organization_id, registry_name, registry_type, registry_category, description,
        is_compliance, frequency, next_due_date, compliance_score, priority_level,
        assigned_owner_id, reference_url, meta_data, created_by
    )
    VALUES (
        gen_random_uuid(), v_dev_org_id, 'ISO 9001:2015 - Quality Management', 'quality', 'quality_management',
        'Quality management system requirements for consistent product quality',
        TRUE, 'annually', NOW() + INTERVAL '180 days', 90, 'high',
        v_dev_user_id, 'https://www.iso.org/standard/72849.html', '{}'::jsonb, v_dev_user_id
    )
    RETURNING id INTO v_iso_registry_id;
    
    -- Create Internal Operational Registries
    
    -- Internal Safety Registry
    INSERT INTO actionable_registries (
        id, organization_id, registry_name, registry_type, registry_category, description,
        is_compliance, frequency, next_due_date, compliance_score, priority_level,
        assigned_owner_id, meta_data, created_by
    )
    VALUES (
        gen_random_uuid(), v_dev_org_id, 'Internal Safety Protocols', 'safety', 'internal_safety',
        'Internal safety procedures and protocols for facility operations',
        FALSE, 'monthly', NOW() + INTERVAL '7 days', 75, 'medium',
        v_dev_user_id, '{}'::jsonb, v_dev_user_id
    )
    RETURNING id INTO v_internal_safety_id;
    
    -- Internal Quality Registry
    INSERT INTO actionable_registries (
        id, organization_id, registry_name, registry_type, registry_category, description,
        is_compliance, frequency, next_due_date, compliance_score, priority_level,
        assigned_owner_id, meta_data, created_by
    )
    VALUES (
        gen_random_uuid(), v_dev_org_id, 'Internal Quality Checks', 'quality', 'internal_quality',
        'Internal quality inspection and verification procedures',
        FALSE, 'weekly', NOW() + INTERVAL '3 days', 80, 'medium',
        v_dev_user_id, '{}'::jsonb, v_dev_user_id
    )
    RETURNING id INTO v_internal_quality_id;
    
    -- Internal Operations Registry
    INSERT INTO actionable_registries (
        id, organization_id, registry_name, registry_type, registry_category, description,
        is_compliance, frequency, next_due_date, compliance_score, priority_level,
        assigned_owner_id, meta_data, created_by
    )
    VALUES (
        gen_random_uuid(), v_dev_org_id, 'Operational Procedures', 'operational', 'procedures',
        'Standard operating procedures for production and logistics',
        FALSE, 'as_needed', NOW() + INTERVAL '14 days', 70, 'low',
        v_dev_user_id, '{}'::jsonb, v_dev_user_id
    )
    RETURNING id INTO v_internal_ops_id;
    
    -- Add OSHA Registry Items
    INSERT INTO actionable_registry_items (registry_id, item_code, item_name, item_description, severity_level, is_required, completion_criteria, verification_method, estimated_effort_minutes, next_due_at, risk_score, meta_data, created_at)
    VALUES 
        (v_osha_registry_id, '1910.147(a)(1)', 'Energy Control Program', 'Establish energy control program for hazardous energy sources', 'critical', TRUE, 'Written program documented and approved', 'documentation', 120, NOW() + INTERVAL '30 days', 90, '{}'::jsonb, NOW()),
        (v_osha_registry_id, '1910.147(b)', 'Lockout/Tagout Training', 'Train all authorized employees on lockout/tagout procedures', 'high', TRUE, 'All employees trained and documented', 'audit', 60, NOW() + INTERVAL '30 days', 75, '{}'::jsonb, NOW()),
        (v_osha_registry_id, '1910.147(c)', 'Periodic Inspection', 'Conduct periodic inspection of lockout/tagout procedures', 'high', TRUE, 'Inspection completed and documented', 'inspection', 30, NOW() + INTERVAL '30 days', 70, '{}'::jsonb, NOW()),
        (v_osha_registry_id, '1910.147(d)', 'Group Lockout', 'Implement group lockout/tagout procedures', 'medium', TRUE, 'Group procedures documented', 'documentation', 45, NOW() + INTERVAL '30 days', 60, '{}'::jsonb, NOW());
    
    -- Add ISO Registry Items
    INSERT INTO actionable_registry_items (registry_id, item_code, item_name, item_description, severity_level, is_required, completion_criteria, verification_method, estimated_effort_minutes, next_due_at, risk_score, meta_data, created_at)
    VALUES 
        (v_iso_registry_id, 'ISO-4.4', 'Quality Management System', 'Establish and maintain quality management system', 'high', TRUE, 'QMS documented and implemented', 'audit', 180, NOW() + INTERVAL '180 days', 80, '{}'::jsonb, NOW()),
        (v_iso_registry_id, 'ISO-8.2', 'Product Realization', 'Implement product realization processes', 'high', TRUE, 'Processes documented and followed', 'inspection', 120, NOW() + INTERVAL '180 days', 75, '{}'::jsonb, NOW()),
        (v_iso_registry_id, 'ISO-8.3', 'Design and Development', 'Control design and development processes', 'medium', TRUE, 'Design procedures documented', 'documentation', 90, NOW() + INTERVAL '180 days', 65, '{}'::jsonb, NOW()),
        (v_iso_registry_id, 'ISO-9.1', 'Monitoring and Measurement', 'Implement monitoring and measurement processes', 'medium', TRUE, 'Monitoring procedures in place', 'test', 60, NOW() + INTERVAL '180 days', 60, '{}'::jsonb, NOW());
    
    -- Add Internal Safety Registry Items
    INSERT INTO actionable_registry_items (registry_id, item_code, item_name, item_description, severity_level, is_required, completion_criteria, verification_method, estimated_effort_minutes, next_due_at, risk_score, meta_data, created_at)
    VALUES 
        (v_internal_safety_id, 'SAFE-001', 'Daily Safety Inspection', 'Daily walkthrough to identify safety hazards', 'high', TRUE, 'Inspection checklist completed', 'inspection', 30, NOW() + INTERVAL '7 days', 70, '{}'::jsonb, NOW()),
        (v_internal_safety_id, 'SAFE-002', 'PPE Compliance Check', 'Verify PPE usage in production areas', 'medium', TRUE, 'PPE compliance verified', 'inspection', 15, NOW() + INTERVAL '7 days', 55, '{}'::jsonb, NOW()),
        (v_internal_safety_id, 'SAFE-003', 'Emergency Exit Inspection', 'Check emergency exits and pathways', 'high', TRUE, 'All exits clear and accessible', 'inspection', 20, NOW() + INTERVAL '7 days', 65, '{}'::jsonb, NOW()),
        (v_internal_safety_id, 'SAFE-004', 'Fire Extinguisher Check', 'Monthly fire extinguisher inspection', 'medium', TRUE, 'All extinguishers inspected and tagged', 'inspection', 25, NOW() + INTERVAL '7 days', 50, '{}'::jsonb, NOW());
    
    -- Add Internal Quality Registry Items
    INSERT INTO actionable_registry_items (registry_id, item_code, item_name, item_description, severity_level, is_required, completion_criteria, verification_method, estimated_effort_minutes, next_due_at, risk_score, meta_data, created_at)
    VALUES 
        (v_internal_quality_id, 'QUAL-001', 'Product Quality Check', 'Daily product quality sampling', 'high', TRUE, 'Quality samples meet specifications', 'test', 45, NOW() + INTERVAL '3 days', 75, '{}'::jsonb, NOW()),
        (v_internal_quality_id, 'QUAL-002', 'Equipment Calibration', 'Verify equipment calibration status', 'medium', TRUE, 'Calibration verified and documented', 'documentation', 30, NOW() + INTERVAL '3 days', 60, '{}'::jsonb, NOW()),
        (v_internal_quality_id, 'QUAL-003', 'Defect Tracking', 'Track and analyze product defects', 'medium', TRUE, 'Defect log updated and analyzed', 'documentation', 20, NOW() + INTERVAL '3 days', 55, '{}'::jsonb, NOW()),
        (v_internal_quality_id, 'QUAL-004', 'Supplier Quality Review', 'Review supplier quality metrics', 'low', TRUE, 'Supplier quality report generated', 'documentation', 60, NOW() + INTERVAL '3 days', 45, '{}'::jsonb, NOW());
    
    -- Add Internal Operations Registry Items
    INSERT INTO actionable_registry_items (registry_id, item_code, item_name, item_description, severity_level, is_required, completion_criteria, verification_method, estimated_effort_minutes, next_due_at, risk_score, meta_data, created_at)
    VALUES 
        (v_internal_ops_id, 'OPS-001', 'Production Line Setup', 'Verify production line configuration', 'high', TRUE, 'Line setup verified per specifications', 'inspection', 60, NOW() + INTERVAL '14 days', 70, '{}'::jsonb, NOW()),
        (v_internal_ops_id, 'OPS-002', 'Inventory Count', 'Conduct inventory count for critical items', 'medium', TRUE, 'Inventory count completed and reconciled', 'documentation', 90, NOW() + INTERVAL '14 days', 55, '{}'::jsonb, NOW()),
        (v_internal_ops_id, 'OPS-003', 'Maintenance Schedule Review', 'Review and update maintenance schedule', 'low', TRUE, 'Maintenance schedule updated', 'documentation', 30, NOW() + INTERVAL '14 days', 40, '{}'::jsonb, NOW()),
        (v_internal_ops_id, 'OPS-004', 'Yard Slot Optimization', 'Optimize yard slot allocation', 'medium', TRUE, 'Yard slots optimized per utilization data', 'documentation', 45, NOW() + INTERVAL '14 days', 50, '{}'::jsonb, NOW());
    
    -- Create sample data correlations
    INSERT INTO data_correlations (organization_id, correlation_type, source_type, source_id, target_type, target_id, correlation_strength, correlation_method, confidence_score, correlation_meta_data, created_by, created_at)
    SELECT 
        v_dev_org_id,
        'task_to_registry_item',
        'task',
        t.id,
        'registry_item',
        ari.id,
        75,
        'ai_suggested',
        80,
        '{}'::jsonb,
        v_dev_user_id,
        NOW()
    FROM tasks t
    CROSS JOIN actionable_registry_items ari
    WHERE t.task_type IN ('maintenance_cm', 'safety_check', 'quality_inspection')
    AND ari.registry_id IN (v_osha_registry_id, v_internal_safety_id, v_internal_quality_id)
    LIMIT 10;
    
    -- Create asset correlations
    INSERT INTO data_correlations (organization_id, correlation_type, source_type, source_id, target_type, target_id, correlation_strength, correlation_method, confidence_score, correlation_meta_data, created_by, created_at)
    SELECT 
        v_dev_org_id,
        'task_to_asset',
        'task',
        t.id,
        'asset',
        a.id,
        90,
        'automated',
        95,
        '{}'::jsonb,
        v_dev_user_id,
        NOW()
    FROM tasks t
    CROSS JOIN assets a
    WHERE t.asset_id IS NOT NULL
    LIMIT 5;
    
    RAISE NOTICE 'Actionable registries sample data populated successfully';
END $$;
