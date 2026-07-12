-- Optional seed: one demo asset + one open alarm for the dev-token org (DEV_ORG_ID in backend/app/api/auth.py).
-- Run manually after compose is up so supervisor Home is not all zeros:
--   docker compose exec -T timescaledb psql -U omniusgrid -d omniusgrid -f /docker-entrypoint-initdb.d/009_dev_floor_sample_data.sql

INSERT INTO assets (
    organization_id,
    workcell_id,
    asset_type_id,
    name,
    serial_number,
    vendor,
    model,
    current_packml_state,
    connection_config,
    is_active,
    last_seen
)
SELECT
    '00000000-0000-0000-0000-000000000001'::uuid,
    w.id,
    t.id,
    'Demo line — 3D printer',
    'DEMO-3DP-001',
    'OmniusGrid',
    'DemoCell',
    'Execute',
    '{"protocol":"demo","note":"seed from 009_dev_floor_sample_data.sql"}'::jsonb,
    TRUE,
    NOW()
FROM (SELECT id FROM asset_types ORDER BY created_at ASC LIMIT 1) AS t
CROSS JOIN (
    SELECT id FROM workcells
    WHERE organization_id = '00000000-0000-0000-0000-000000000001'::uuid
    ORDER BY created_at ASC LIMIT 1
) AS w
WHERE NOT EXISTS (
    SELECT 1
    FROM assets a
    WHERE a.organization_id = '00000000-0000-0000-0000-000000000001'::uuid
      AND a.serial_number = 'DEMO-3DP-001'
);

INSERT INTO alarms (
    asset_id,
    alarm_code,
    severity,
    message,
    description,
    is_active,
    is_acknowledged,
    occurred_at,
    metadata
)
SELECT
    a.id,
    'DEMO-001',
    'high',
    'Demo alarm: check coolant flow',
    'Seeded for supervisor UI; clear or acknowledge in the app.',
    TRUE,
    FALSE,
    NOW(),
    '{}'::jsonb
FROM assets a
WHERE a.organization_id = '00000000-0000-0000-0000-000000000001'::uuid
  AND a.serial_number = 'DEMO-3DP-001'
  AND NOT EXISTS (
    SELECT 1
    FROM alarms al
    WHERE al.asset_id = a.id
      AND al.alarm_code = 'DEMO-001'
      AND al.is_active = TRUE
  )
LIMIT 1;
