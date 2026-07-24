-- 045_backfill_null_timestamps.sql
--
-- Repair created_at/updated_at rows that were written as NULL before migration
-- 044 added the server defaults (FS-202 follow-up).
--
-- 044 stopped NEW raw-SQL inserts from writing NULL. Rows already written that
-- way are still invisible to every time-ordered query and to the dashboard
-- trends, so they are repaired here.
--
-- The values are DERIVED, not invented. For each table we use a timestamp on
-- the row itself that the row must already have existed by — a check-in, a trip
-- start, a first-seen, a scheduled pickup. That is an upper bound on creation
-- time, which is a real inference rather than a fabricated one. Where the row
-- carries nothing usable (carriers/drivers hold only FUTURE expiry dates;
-- routes and analysis_sessions hold none) we fall back to the earliest
-- created_at the table itself already knows, and only then to NOW().
--
-- updated_at is set to the repaired created_at: a row never modified since
-- creation genuinely has updated_at = created_at.
--
-- Idempotent: every statement is WHERE created_at IS NULL, so re-running is a
-- no-op, and each is guarded on the table/column existing.


DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_trailers' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_trailers' AND column_name='check_in_at') THEN
    UPDATE yard_trailers SET created_at = COALESCE(check_in_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_moves' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_moves' AND column_name='started_at') THEN
    UPDATE yard_moves SET created_at = COALESCE(started_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_checkpoints' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_checkpoints' AND column_name='passed_at') THEN
    UPDATE yard_checkpoints SET created_at = COALESCE(passed_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='driver_wait_times' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='driver_wait_times' AND column_name='check_in_at') THEN
    UPDATE driver_wait_times SET created_at = COALESCE(check_in_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_trips' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_trips' AND column_name='start_time') THEN
    UPDATE geotab_trips SET created_at = COALESCE(start_time, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_diagnostics' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_diagnostics' AND column_name='first_seen_at') THEN
    UPDATE geotab_diagnostics SET created_at = COALESCE(first_seen_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_exceptions' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_exceptions' AND column_name='timestamp') THEN
    UPDATE geotab_exceptions SET created_at = COALESCE(timestamp, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='truck_asset_correlations' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='truck_asset_correlations' AND column_name='truck_arrived_at') THEN
    UPDATE truck_asset_correlations SET created_at = COALESCE(truck_arrived_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='load_plans' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='load_plans' AND column_name='planned_at') THEN
    UPDATE load_plans SET created_at = COALESCE(planned_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dock_appointments' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dock_appointments' AND column_name='scheduled_start') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dock_appointments' AND column_name='actual_start') THEN
    UPDATE dock_appointments SET created_at = COALESCE(LEAST(scheduled_start, actual_start), NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='shipments' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='shipments' AND column_name='scheduled_pickup') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='shipments' AND column_name='actual_pickup') THEN
    UPDATE shipments SET created_at = COALESCE(LEAST(scheduled_pickup, actual_pickup), NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='freight_charges' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='freight_charges' AND column_name='billed_at') THEN
    UPDATE freight_charges SET created_at = COALESCE(billed_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='intake_items' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='intake_items' AND column_name='analyzed_at') THEN
    UPDATE intake_items SET created_at = COALESCE(analyzed_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='load_quality_logs' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='load_quality_logs' AND column_name='resolved_at') THEN
    UPDATE load_quality_logs SET created_at = COALESCE(resolved_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dock_doors' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dock_doors' AND column_name='last_occupied_at') THEN
    UPDATE dock_doors SET created_at = COALESCE(last_occupied_at, NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='carriers' AND column_name='created_at') THEN
    UPDATE carriers SET created_at = COALESCE(
             (SELECT MIN(created_at) FROM carriers WHERE created_at IS NOT NULL),
             NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='drivers' AND column_name='created_at') THEN
    UPDATE drivers SET created_at = COALESCE(
             (SELECT MIN(created_at) FROM drivers WHERE created_at IS NOT NULL),
             NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='routes' AND column_name='created_at') THEN
    UPDATE routes SET created_at = COALESCE(
             (SELECT MIN(created_at) FROM routes WHERE created_at IS NOT NULL),
             NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='analysis_sessions' AND column_name='created_at') THEN
    UPDATE analysis_sessions SET created_at = COALESCE(
             (SELECT MIN(created_at) FROM analysis_sessions WHERE created_at IS NOT NULL),
             NOW())
     WHERE created_at IS NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_trailers' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_trailers' AND column_name='updated_at') THEN
    UPDATE yard_trailers SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_moves' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_moves' AND column_name='updated_at') THEN
    UPDATE yard_moves SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_checkpoints' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='yard_checkpoints' AND column_name='updated_at') THEN
    UPDATE yard_checkpoints SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='driver_wait_times' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='driver_wait_times' AND column_name='updated_at') THEN
    UPDATE driver_wait_times SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_trips' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_trips' AND column_name='updated_at') THEN
    UPDATE geotab_trips SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_diagnostics' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_diagnostics' AND column_name='updated_at') THEN
    UPDATE geotab_diagnostics SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_exceptions' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='geotab_exceptions' AND column_name='updated_at') THEN
    UPDATE geotab_exceptions SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='truck_asset_correlations' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='truck_asset_correlations' AND column_name='updated_at') THEN
    UPDATE truck_asset_correlations SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='load_plans' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='load_plans' AND column_name='updated_at') THEN
    UPDATE load_plans SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dock_appointments' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dock_appointments' AND column_name='updated_at') THEN
    UPDATE dock_appointments SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='shipments' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='shipments' AND column_name='updated_at') THEN
    UPDATE shipments SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='freight_charges' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='freight_charges' AND column_name='updated_at') THEN
    UPDATE freight_charges SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='intake_items' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='intake_items' AND column_name='updated_at') THEN
    UPDATE intake_items SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='load_quality_logs' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='load_quality_logs' AND column_name='updated_at') THEN
    UPDATE load_quality_logs SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dock_doors' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dock_doors' AND column_name='updated_at') THEN
    UPDATE dock_doors SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='carriers' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='carriers' AND column_name='updated_at') THEN
    UPDATE carriers SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='drivers' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='drivers' AND column_name='updated_at') THEN
    UPDATE drivers SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='routes' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='routes' AND column_name='updated_at') THEN
    UPDATE routes SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='analysis_sessions' AND column_name='created_at') AND EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='analysis_sessions' AND column_name='updated_at') THEN
    UPDATE analysis_sessions SET updated_at = created_at
     WHERE updated_at IS NULL AND created_at IS NOT NULL;
  END IF;
END $$;
