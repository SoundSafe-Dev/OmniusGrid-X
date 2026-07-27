-- 050_logistics_server_defaults.sql
--
-- Give 39 logistics/yard columns a SERVER default (continues FS-202).
--
-- Migration 044 did this for created_at/updated_at across 30 tables. The columns
-- below are the same defect in the same shape, on the tables 044 did not reach:
-- declared in the ORM as `Column(..., default=X)`, which is a PYTHON-side default
-- that fires ONLY when the row is written through SQLAlchemy. Migration 030 was
-- generated from that same metadata, so it emitted them as plain nullable columns
-- with no DEFAULT.
--
-- Consequence: any raw-SQL INSERT -- a seed script, COPY, a worker bulk insert, a
-- psql fix-up -- writes NULL, and then the API cannot serialise the row at all.
-- That is not hypothetical: a dock door inserted this way made
-- GET /api/v1/yard/dock/doors return 500 with "equipment_capabilities: Input
-- should be a valid dictionary" -- a validation error naming our schema rather
-- than the data, so nobody would think to look at the row.
--
-- Each default is taken from the ORM's own `default=`, so the database now
-- enforces exactly what the application already assumed.
--
-- UNLIKE 044, existing NULLs ARE backfilled here. 044 deliberately left NULL
-- timestamps alone, because stamping a row's creation time with NOW() would
-- fabricate history. These columns carry no such meaning -- a NULL `is_active`
-- or `status` is a missing value, not an unknown moment -- so writing the
-- documented default is a correction, not an invention. The one exception in
-- spirit is the four DATETIME columns below (check_in_at, started_at, passed_at,
-- planned_at, session timestamp); they are backfilled because a row that records
-- an event which demonstrably happened is more wrong with a NULL timestamp than
-- with the migration's timestamp, and they are operational markers rather than
-- audit history.
--
-- Idempotent: SET DEFAULT is repeatable, the UPDATE is a no-op on a second run,
-- and every statement is guarded so the migration is safe where a table is absent.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'carriers' AND column_name = 'contact_info'
  ) THEN
    EXECUTE 'ALTER TABLE carriers ALTER COLUMN contact_info SET DEFAULT ''{}''::jsonb';
    UPDATE carriers SET contact_info = '{}'::jsonb WHERE contact_info IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'carriers' AND column_name = 'contract_rate'
  ) THEN
    EXECUTE 'ALTER TABLE carriers ALTER COLUMN contract_rate SET DEFAULT ''{}''::jsonb';
    UPDATE carriers SET contract_rate = '{}'::jsonb WHERE contract_rate IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'carriers' AND column_name = 'ctpat_certified'
  ) THEN
    EXECUTE 'ALTER TABLE carriers ALTER COLUMN ctpat_certified SET DEFAULT false';
    UPDATE carriers SET ctpat_certified = false WHERE ctpat_certified IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'carriers' AND column_name = 'insurance_on_file'
  ) THEN
    EXECUTE 'ALTER TABLE carriers ALTER COLUMN insurance_on_file SET DEFAULT false';
    UPDATE carriers SET insurance_on_file = false WHERE insurance_on_file IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'carriers' AND column_name = 'is_active'
  ) THEN
    EXECUTE 'ALTER TABLE carriers ALTER COLUMN is_active SET DEFAULT true';
    UPDATE carriers SET is_active = true WHERE is_active IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'dock_appointments' AND column_name = 'compliance_required'
  ) THEN
    EXECUTE 'ALTER TABLE dock_appointments ALTER COLUMN compliance_required SET DEFAULT false';
    UPDATE dock_appointments SET compliance_required = false WHERE compliance_required IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'dock_appointments' AND column_name = 'priority'
  ) THEN
    EXECUTE 'ALTER TABLE dock_appointments ALTER COLUMN priority SET DEFAULT ''normal''';
    UPDATE dock_appointments SET priority = 'normal' WHERE priority IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'dock_appointments' AND column_name = 'status'
  ) THEN
    EXECUTE 'ALTER TABLE dock_appointments ALTER COLUMN status SET DEFAULT ''scheduled''';
    UPDATE dock_appointments SET status = 'scheduled' WHERE status IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'driver_wait_times' AND column_name = 'is_billed'
  ) THEN
    EXECUTE 'ALTER TABLE driver_wait_times ALTER COLUMN is_billed SET DEFAULT false';
    UPDATE driver_wait_times SET is_billed = false WHERE is_billed IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'drivers' AND column_name = 'dq_file_complete'
  ) THEN
    EXECUTE 'ALTER TABLE drivers ALTER COLUMN dq_file_complete SET DEFAULT false';
    UPDATE drivers SET dq_file_complete = false WHERE dq_file_complete IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'drivers' AND column_name = 'hazmat_endorsed'
  ) THEN
    EXECUTE 'ALTER TABLE drivers ALTER COLUMN hazmat_endorsed SET DEFAULT false';
    UPDATE drivers SET hazmat_endorsed = false WHERE hazmat_endorsed IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'drivers' AND column_name = 'hos_cycle_hours'
  ) THEN
    EXECUTE 'ALTER TABLE drivers ALTER COLUMN hos_cycle_hours SET DEFAULT 0';
    UPDATE drivers SET hos_cycle_hours = 0 WHERE hos_cycle_hours IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'drivers' AND column_name = 'hos_drive_hours_today'
  ) THEN
    EXECUTE 'ALTER TABLE drivers ALTER COLUMN hos_drive_hours_today SET DEFAULT 0';
    UPDATE drivers SET hos_drive_hours_today = 0 WHERE hos_drive_hours_today IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'drivers' AND column_name = 'hos_on_duty_hours_today'
  ) THEN
    EXECUTE 'ALTER TABLE drivers ALTER COLUMN hos_on_duty_hours_today SET DEFAULT 0';
    UPDATE drivers SET hos_on_duty_hours_today = 0 WHERE hos_on_duty_hours_today IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'drivers' AND column_name = 'is_active'
  ) THEN
    EXECUTE 'ALTER TABLE drivers ALTER COLUMN is_active SET DEFAULT true';
    UPDATE drivers SET is_active = true WHERE is_active IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'freight_charges' AND column_name = 'currency'
  ) THEN
    EXECUTE 'ALTER TABLE freight_charges ALTER COLUMN currency SET DEFAULT ''USD''';
    UPDATE freight_charges SET currency = 'USD' WHERE currency IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'freight_charges' AND column_name = 'is_billed'
  ) THEN
    EXECUTE 'ALTER TABLE freight_charges ALTER COLUMN is_billed SET DEFAULT false';
    UPDATE freight_charges SET is_billed = false WHERE is_billed IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_plans' AND column_name = 'is_executed'
  ) THEN
    EXECUTE 'ALTER TABLE load_plans ALTER COLUMN is_executed SET DEFAULT false';
    UPDATE load_plans SET is_executed = false WHERE is_executed IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_plans' AND column_name = 'load_sequence'
  ) THEN
    EXECUTE 'ALTER TABLE load_plans ALTER COLUMN load_sequence SET DEFAULT ''[]''::jsonb';
    UPDATE load_plans SET load_sequence = '[]'::jsonb WHERE load_sequence IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_plans' AND column_name = 'planned_at'
  ) THEN
    EXECUTE 'ALTER TABLE load_plans ALTER COLUMN planned_at SET DEFAULT NOW()';
    UPDATE load_plans SET planned_at = NOW() WHERE planned_at IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_plans' AND column_name = 'temperature_zones'
  ) THEN
    EXECUTE 'ALTER TABLE load_plans ALTER COLUMN temperature_zones SET DEFAULT ''[]''::jsonb';
    UPDATE load_plans SET temperature_zones = '[]'::jsonb WHERE temperature_zones IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_plans' AND column_name = 'weight_distribution'
  ) THEN
    EXECUTE 'ALTER TABLE load_plans ALTER COLUMN weight_distribution SET DEFAULT ''{}''::jsonb';
    UPDATE load_plans SET weight_distribution = '{}'::jsonb WHERE weight_distribution IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_quality_logs' AND column_name = 'carrier_liable'
  ) THEN
    EXECUTE 'ALTER TABLE load_quality_logs ALTER COLUMN carrier_liable SET DEFAULT false';
    UPDATE load_quality_logs SET carrier_liable = false WHERE carrier_liable IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_quality_logs' AND column_name = 'claim_filed'
  ) THEN
    EXECUTE 'ALTER TABLE load_quality_logs ALTER COLUMN claim_filed SET DEFAULT false';
    UPDATE load_quality_logs SET claim_filed = false WHERE claim_filed IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'routes' AND column_name = 'is_active'
  ) THEN
    EXECUTE 'ALTER TABLE routes ALTER COLUMN is_active SET DEFAULT true';
    UPDATE routes SET is_active = true WHERE is_active IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'routes' AND column_name = 'waypoints'
  ) THEN
    EXECUTE 'ALTER TABLE routes ALTER COLUMN waypoints SET DEFAULT ''[]''::jsonb';
    UPDATE routes SET waypoints = '[]'::jsonb WHERE waypoints IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'session_messages' AND column_name = 'timestamp'
  ) THEN
    EXECUTE 'ALTER TABLE session_messages ALTER COLUMN timestamp SET DEFAULT NOW()';
    UPDATE session_messages SET timestamp = NOW() WHERE timestamp IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'shipments' AND column_name = 'destination'
  ) THEN
    EXECUTE 'ALTER TABLE shipments ALTER COLUMN destination SET DEFAULT ''{}''::jsonb';
    UPDATE shipments SET destination = '{}'::jsonb WHERE destination IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'shipments' AND column_name = 'hazmat'
  ) THEN
    EXECUTE 'ALTER TABLE shipments ALTER COLUMN hazmat SET DEFAULT false';
    UPDATE shipments SET hazmat = false WHERE hazmat IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'shipments' AND column_name = 'origin'
  ) THEN
    EXECUTE 'ALTER TABLE shipments ALTER COLUMN origin SET DEFAULT ''{}''::jsonb';
    UPDATE shipments SET origin = '{}'::jsonb WHERE origin IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'shipments' AND column_name = 'priority'
  ) THEN
    EXECUTE 'ALTER TABLE shipments ALTER COLUMN priority SET DEFAULT ''normal''';
    UPDATE shipments SET priority = 'normal' WHERE priority IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'shipments' AND column_name = 'status'
  ) THEN
    EXECUTE 'ALTER TABLE shipments ALTER COLUMN status SET DEFAULT ''planned''';
    UPDATE shipments SET status = 'planned' WHERE status IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'shipments' AND column_name = 'temperature_required'
  ) THEN
    EXECUTE 'ALTER TABLE shipments ALTER COLUMN temperature_required SET DEFAULT false';
    UPDATE shipments SET temperature_required = false WHERE temperature_required IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'truck_asset_correlations' AND column_name = 'detention_incurred'
  ) THEN
    EXECUTE 'ALTER TABLE truck_asset_correlations ALTER COLUMN detention_incurred SET DEFAULT false';
    UPDATE truck_asset_correlations SET detention_incurred = false WHERE detention_incurred IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'yard_checkpoints' AND column_name = 'passed_at'
  ) THEN
    EXECUTE 'ALTER TABLE yard_checkpoints ALTER COLUMN passed_at SET DEFAULT NOW()';
    UPDATE yard_checkpoints SET passed_at = NOW() WHERE passed_at IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'yard_moves' AND column_name = 'started_at'
  ) THEN
    EXECUTE 'ALTER TABLE yard_moves ALTER COLUMN started_at SET DEFAULT NOW()';
    UPDATE yard_moves SET started_at = NOW() WHERE started_at IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'yard_trailers' AND column_name = 'check_in_at'
  ) THEN
    EXECUTE 'ALTER TABLE yard_trailers ALTER COLUMN check_in_at SET DEFAULT NOW()';
    UPDATE yard_trailers SET check_in_at = NOW() WHERE check_in_at IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'yard_trailers' AND column_name = 'seal_status'
  ) THEN
    EXECUTE 'ALTER TABLE yard_trailers ALTER COLUMN seal_status SET DEFAULT ''intact''';
    UPDATE yard_trailers SET seal_status = 'intact' WHERE seal_status IS NULL;
  END IF;
END $$;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'yard_trailers' AND column_name = 'status'
  ) THEN
    EXECUTE 'ALTER TABLE yard_trailers ALTER COLUMN status SET DEFAULT ''checked_in''';
    UPDATE yard_trailers SET status = 'checked_in' WHERE status IS NULL;
  END IF;
END $$;
