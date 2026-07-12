-- 033_rls_backfill.sql (FS-56)
-- Re-applies 011's tenant-isolation policies. 011 runs before 030 creates the
-- yard/transportation/geotab/session tables, so its per-table guards skip them
-- on a fresh migrations build; this file runs after 030/032 when every table
-- exists. All statements are the same guarded, idempotent DO blocks
-- (DROP POLICY IF EXISTS + CREATE POLICY), so re-running is safe everywhere.

-- T: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.T') IS NOT NULL THEN
    -- -----------------------------------------------------------------------------
    -- Helper macro pattern (documented, not implemented as a function — the
    -- DDL below is intentionally repetitive so it's easy to grep / review).
    --
    -- For each strict-RLS table T:
    --   ALTER TABLE T ENABLE ROW LEVEL SECURITY;
    --   ALTER TABLE T FORCE  ROW LEVEL SECURITY;
    --   DROP POLICY IF EXISTS tenant_isolation ON T;
    --   CREATE POLICY tenant_isolation ON T
    --     FOR ALL
    --     USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    --     WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
    --
    -- For permissive-RLS tables the predicate is:
    --   (organization_id IS NULL OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
    -- -----------------------------------------------------------------------------
  END IF;
END $$;

-- assets: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.assets') IS NOT NULL THEN
    -- ---- Core manufacturing ----
    ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
    ALTER TABLE assets FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON assets;
    CREATE POLICY tenant_isolation ON assets
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- workcells: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.workcells') IS NOT NULL THEN
    ALTER TABLE workcells ENABLE ROW LEVEL SECURITY;
    ALTER TABLE workcells FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON workcells;
    CREATE POLICY tenant_isolation ON workcells
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- commands: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.commands') IS NOT NULL THEN
    ALTER TABLE commands ENABLE ROW LEVEL SECURITY;
    ALTER TABLE commands FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON commands;
    CREATE POLICY tenant_isolation ON commands
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- yard_trailers: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.yard_trailers') IS NOT NULL THEN
    -- ---- Yard management ----
    ALTER TABLE yard_trailers ENABLE ROW LEVEL SECURITY;
    ALTER TABLE yard_trailers FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON yard_trailers;
    CREATE POLICY tenant_isolation ON yard_trailers
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- dock_doors: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.dock_doors') IS NOT NULL THEN
    ALTER TABLE dock_doors ENABLE ROW LEVEL SECURITY;
    ALTER TABLE dock_doors FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON dock_doors;
    CREATE POLICY tenant_isolation ON dock_doors
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- yard_moves: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.yard_moves') IS NOT NULL THEN
    ALTER TABLE yard_moves ENABLE ROW LEVEL SECURITY;
    ALTER TABLE yard_moves FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON yard_moves;
    CREATE POLICY tenant_isolation ON yard_moves
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- driver_wait_times: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.driver_wait_times') IS NOT NULL THEN
    ALTER TABLE driver_wait_times ENABLE ROW LEVEL SECURITY;
    ALTER TABLE driver_wait_times FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON driver_wait_times;
    CREATE POLICY tenant_isolation ON driver_wait_times
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- yard_checkpoints: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.yard_checkpoints') IS NOT NULL THEN
    ALTER TABLE yard_checkpoints ENABLE ROW LEVEL SECURITY;
    ALTER TABLE yard_checkpoints FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON yard_checkpoints;
    CREATE POLICY tenant_isolation ON yard_checkpoints
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- carriers: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.carriers') IS NOT NULL THEN
    -- ---- Transportation / logistics ----
    ALTER TABLE carriers ENABLE ROW LEVEL SECURITY;
    ALTER TABLE carriers FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON carriers;
    CREATE POLICY tenant_isolation ON carriers
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- drivers: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.drivers') IS NOT NULL THEN
    ALTER TABLE drivers ENABLE ROW LEVEL SECURITY;
    ALTER TABLE drivers FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON drivers;
    CREATE POLICY tenant_isolation ON drivers
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- shipments: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.shipments') IS NOT NULL THEN
    ALTER TABLE shipments ENABLE ROW LEVEL SECURITY;
    ALTER TABLE shipments FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON shipments;
    CREATE POLICY tenant_isolation ON shipments
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- routes: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.routes') IS NOT NULL THEN
    ALTER TABLE routes ENABLE ROW LEVEL SECURITY;
    ALTER TABLE routes FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON routes;
    CREATE POLICY tenant_isolation ON routes
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- load_plans: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.load_plans') IS NOT NULL THEN
    ALTER TABLE load_plans ENABLE ROW LEVEL SECURITY;
    ALTER TABLE load_plans FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON load_plans;
    CREATE POLICY tenant_isolation ON load_plans
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- freight_charges: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.freight_charges') IS NOT NULL THEN
    ALTER TABLE freight_charges ENABLE ROW LEVEL SECURITY;
    ALTER TABLE freight_charges FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON freight_charges;
    CREATE POLICY tenant_isolation ON freight_charges
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- dock_appointments: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.dock_appointments') IS NOT NULL THEN
    ALTER TABLE dock_appointments ENABLE ROW LEVEL SECURITY;
    ALTER TABLE dock_appointments FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON dock_appointments;
    CREATE POLICY tenant_isolation ON dock_appointments
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- truck_asset_correlations: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.truck_asset_correlations') IS NOT NULL THEN
    ALTER TABLE truck_asset_correlations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE truck_asset_correlations FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON truck_asset_correlations;
    CREATE POLICY tenant_isolation ON truck_asset_correlations
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- load_quality_logs: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.load_quality_logs') IS NOT NULL THEN
    ALTER TABLE load_quality_logs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE load_quality_logs FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON load_quality_logs;
    CREATE POLICY tenant_isolation ON load_quality_logs
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- task_boards: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.task_boards') IS NOT NULL THEN
    -- ---- Kanban / task management ----
    ALTER TABLE task_boards ENABLE ROW LEVEL SECURITY;
    ALTER TABLE task_boards FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON task_boards;
    CREATE POLICY tenant_isolation ON task_boards
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- task_rules: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.task_rules') IS NOT NULL THEN
    ALTER TABLE task_rules ENABLE ROW LEVEL SECURITY;
    ALTER TABLE task_rules FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON task_rules;
    CREATE POLICY tenant_isolation ON task_rules
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- actionable_registries: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.actionable_registries') IS NOT NULL THEN
    ALTER TABLE actionable_registries ENABLE ROW LEVEL SECURITY;
    ALTER TABLE actionable_registries FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON actionable_registries;
    CREATE POLICY tenant_isolation ON actionable_registries
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- data_correlations: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.data_correlations') IS NOT NULL THEN
    -- ---- Correlation / analysis ----
    ALTER TABLE data_correlations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE data_correlations FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON data_correlations;
    CREATE POLICY tenant_isolation ON data_correlations
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- analysis_sessions: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.analysis_sessions') IS NOT NULL THEN
    ALTER TABLE analysis_sessions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE analysis_sessions FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON analysis_sessions;
    CREATE POLICY tenant_isolation ON analysis_sessions
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- intake_items: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.intake_items') IS NOT NULL THEN
    ALTER TABLE intake_items ENABLE ROW LEVEL SECURITY;
    ALTER TABLE intake_items FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON intake_items;
    CREATE POLICY tenant_isolation ON intake_items
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- geotab_trips: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.geotab_trips') IS NOT NULL THEN
    ALTER TABLE geotab_trips ENABLE ROW LEVEL SECURITY;
    ALTER TABLE geotab_trips FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON geotab_trips;
    CREATE POLICY tenant_isolation ON geotab_trips
      FOR ALL
      USING      (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- geotab_diagnostics: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.geotab_diagnostics') IS NOT NULL THEN
    ALTER TABLE geotab_diagnostics ENABLE ROW LEVEL SECURITY;
    ALTER TABLE geotab_diagnostics FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON geotab_diagnostics;
    CREATE POLICY tenant_isolation ON geotab_diagnostics
      FOR ALL
      USING      (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- geotab_exceptions: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.geotab_exceptions') IS NOT NULL THEN
    ALTER TABLE geotab_exceptions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE geotab_exceptions FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON geotab_exceptions;
    CREATE POLICY tenant_isolation ON geotab_exceptions
      FOR ALL
      USING      (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- audit_logs: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.audit_logs') IS NOT NULL THEN
    ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE audit_logs FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON audit_logs;
    CREATE POLICY tenant_isolation ON audit_logs
      FOR ALL
      USING      (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- data_processing_records: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.data_processing_records') IS NOT NULL THEN
    ALTER TABLE data_processing_records ENABLE ROW LEVEL SECURITY;
    ALTER TABLE data_processing_records FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON data_processing_records;
    CREATE POLICY tenant_isolation ON data_processing_records
      FOR ALL
      USING      (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- integration_configurations: guarded — created later in the chain (030) on fresh builds;
-- 033_rls_backfill re-applies for tables this skips.
DO $$
BEGIN
  IF to_regclass('public.integration_configurations') IS NOT NULL THEN
    ALTER TABLE integration_configurations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE integration_configurations FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON integration_configurations;
    CREATE POLICY tenant_isolation ON integration_configurations
      FOR ALL
      USING      (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id IS NULL
                  OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;

-- 021's intake/session columns (021 runs pre-030 and skips on fresh builds)
DO $$
BEGIN
  IF to_regclass('public.intake_items') IS NOT NULL THEN
    ALTER TABLE intake_items
    ADD COLUMN IF NOT EXISTS shared_keys JSON DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS structure_metadata JSON DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS processing_time_seconds INTEGER;

    CREATE INDEX IF NOT EXISTS idx_intake_items_shared_keys
        ON intake_items USING GIN ((shared_keys::jsonb));

    COMMENT ON COLUMN intake_items.shared_keys IS 'Normalized shared keys (asset_id, date, order_number, etc.) extracted from filename, metadata, and content for cross-file correlation';
    COMMENT ON COLUMN intake_items.structure_metadata IS 'Document structure info (page_count, section_count, tables, headers) for PDF/DOCX/image parsing';
    COMMENT ON COLUMN intake_items.processing_time_seconds IS 'Actual time in seconds taken to parse and process the file (for estimation calibration)';
  END IF;

  IF to_regclass('public.session_data_sources') IS NOT NULL THEN
    ALTER TABLE session_data_sources
    ADD COLUMN IF NOT EXISTS shared_keys JSON DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS structure_metadata JSON DEFAULT '{}';

    CREATE INDEX IF NOT EXISTS idx_session_data_sources_shared_keys
        ON session_data_sources USING GIN ((shared_keys::jsonb));

    COMMENT ON COLUMN session_data_sources.shared_keys IS 'Normalized shared keys for cross-file correlation within analysis sessions';
    COMMENT ON COLUMN session_data_sources.structure_metadata IS 'Document structure info for session data sources';
  END IF;
END $$;
