-- 044_timestamp_server_defaults.sql
--
-- Give created_at/updated_at a SERVER default (FS-202).
--
-- 30 of ~60 timestamp columns were declared in the ORM as
--     Column(DateTime(timezone=True), default=utcnow)
-- which is a PYTHON-side default: it only fires when the row is written through
-- SQLAlchemy. Migration 030 was generated from that same ORM metadata, so it
-- emitted these columns as plain nullable TIMESTAMPTZ with no DEFAULT.
--
-- Consequence: any raw-SQL INSERT — seed scripts, COPY, worker bulk inserts, a
-- psql fix-up — writes NULL to created_at/updated_at, and those rows then
-- silently disappear from every time-ordered query and trend (including the
-- dashboard aggregates added in FS-192). It fails quiet, like the RLS class in
-- FS-201.
--
-- Existing NULLs are deliberately NOT backfilled: we cannot know when those rows
-- were really created, and stamping them with NOW() would fabricate history.
-- A visible NULL is more honest than a confident wrong timestamp.
--
-- Idempotent: SET DEFAULT is repeatable, and each statement is guarded so the
-- migration is safe to re-run and safe on databases where a table is absent.


DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'analysis_sessions' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE analysis_sessions ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'analysis_sessions' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE analysis_sessions ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'carriers' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE carriers ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'carriers' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE carriers ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'dock_appointments' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE dock_appointments ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'dock_appointments' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE dock_appointments ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'dock_doors' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE dock_doors ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'dock_doors' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE dock_doors ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'driver_wait_times' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE driver_wait_times ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'driver_wait_times' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE driver_wait_times ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'drivers' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE drivers ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'drivers' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE drivers ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'freight_charges' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE freight_charges ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'freight_charges' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE freight_charges ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'geotab_diagnostics' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE geotab_diagnostics ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'geotab_diagnostics' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE geotab_diagnostics ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'geotab_exceptions' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE geotab_exceptions ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'geotab_trips' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE geotab_trips ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'geotab_trips' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE geotab_trips ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'intake_items' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE intake_items ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_plans' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE load_plans ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_plans' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE load_plans ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_quality_logs' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE load_quality_logs ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'load_quality_logs' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE load_quality_logs ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'routes' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE routes ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'routes' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE routes ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'shipments' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE shipments ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'shipments' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE shipments ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'truck_asset_correlations' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE truck_asset_correlations ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'yard_checkpoints' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE yard_checkpoints ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'yard_moves' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE yard_moves ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'yard_trailers' AND column_name = 'created_at'
  ) THEN
    ALTER TABLE yard_trailers ALTER COLUMN created_at SET DEFAULT NOW();
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'yard_trailers' AND column_name = 'updated_at'
  ) THEN
    ALTER TABLE yard_trailers ALTER COLUMN updated_at SET DEFAULT NOW();
  END IF;
END $$;
