-- =============================================================================
-- Migration 011: Tenant Isolation via Postgres Row Level Security (RLS)
-- =============================================================================
--
-- Purpose
-- -------
-- Defense-in-depth security at the database layer. Complements the
-- application-layer enforcement added in PR #2/3 (`get_tenant_org_id`
-- dependency on assets/telemetry endpoints). If a future endpoint
-- forgets to filter by organization_id, Postgres itself refuses to
-- return cross-tenant rows.
--
-- How it works
-- ------------
-- Each request sets the GUC `app.current_org_id` (connection/session
-- scoped, reset when the request finishes) derived from the
-- authenticated user's JWT (see `get_tenant_db` in
-- `backend/app/core/tenant.py`). Session scope is required because some
-- endpoints commit mid-request and then issue further queries; a
-- transaction-local (`SET LOCAL`) value would be lost after that commit.
-- Policies use `NULLIF(current_setting(...), '')::uuid` so that an unset
-- or reset (empty) value becomes NULL and matches no rows — i.e. queries
-- return zero rows from RLS-protected tables (fail-closed) rather than
-- erroring on an invalid empty UUID.
--
-- Scope
-- -----
-- 29 of the 31 tenant-scoped tables receive RLS:
--   * 23 strict-RLS tables (NOT NULL organization_id):
--       assets, workcells, yard_trailers, dock_doors, yard_moves,
--       driver_wait_times, yard_checkpoints, carriers, drivers,
--       shipments, routes, load_plans, freight_charges, dock_appointments,
--       truck_asset_correlations, load_quality_logs, commands,
--       task_boards, task_rules, actionable_registries,
--       data_correlations, analysis_sessions, intake_items
--   * 6 permissive-RLS tables (nullable organization_id; NULL means global):
--       geotab_trips, geotab_diagnostics, geotab_exceptions,
--       audit_logs, data_processing_records, integration_configurations
--
-- 2 tables are intentionally EXCLUDED from RLS:
--   * users    — accessed by email during /auth/login BEFORE any org
--                context exists; adding RLS here would break login.
--   * api_keys — accessed by key hash during API-key authentication
--                BEFORE any org context exists.
--   Both remain protected by application-layer enforcement. A follow-up
--   could re-enable RLS here via SECURITY DEFINER lookup functions.
--
-- Operational notes
-- -----------------
-- 1. SUPERUSER CAVEAT: Postgres superusers bypass RLS even with FORCE.
--    The dev compose stack creates `omniusgrid` as a superuser via
--    POSTGRES_USER, so RLS is silently a no-op against the dev DB.
--    Production deployments MUST connect the application as a
--    non-superuser role for RLS to actually take effect. The Task 5
--    integration tests verify the policies work against a non-superuser
--    role inside an ephemeral test Postgres.
--
-- 2. Background services (websocket_manager, command_executor,
--    oee_calculator) currently use the un-scoped `get_db` session.
--    Under RLS-enforced production they will need to set
--    `app.current_org_id` per record they process, or run as a separate
--    role that bypasses RLS. Not addressed in this migration — flagged
--    as follow-up work.
--
-- 3. Idempotent: every `CREATE POLICY` is preceded by
--    `DROP POLICY IF EXISTS`, and `ENABLE ROW LEVEL SECURITY` is itself
--    idempotent. Safe to re-apply.
-- =============================================================================

BEGIN;

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


-- =============================================================================
-- STRICT RLS (23 tables): organization_id is NOT NULL
-- =============================================================================

-- ---- Core manufacturing ----
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE assets FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON assets;
CREATE POLICY tenant_isolation ON assets
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE workcells ENABLE ROW LEVEL SECURITY;
ALTER TABLE workcells FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON workcells;
CREATE POLICY tenant_isolation ON workcells
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE commands FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON commands;
CREATE POLICY tenant_isolation ON commands
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

-- ---- Yard management ----
ALTER TABLE yard_trailers ENABLE ROW LEVEL SECURITY;
ALTER TABLE yard_trailers FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON yard_trailers;
CREATE POLICY tenant_isolation ON yard_trailers
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE dock_doors ENABLE ROW LEVEL SECURITY;
ALTER TABLE dock_doors FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON dock_doors;
CREATE POLICY tenant_isolation ON dock_doors
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE yard_moves ENABLE ROW LEVEL SECURITY;
ALTER TABLE yard_moves FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON yard_moves;
CREATE POLICY tenant_isolation ON yard_moves
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE driver_wait_times ENABLE ROW LEVEL SECURITY;
ALTER TABLE driver_wait_times FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON driver_wait_times;
CREATE POLICY tenant_isolation ON driver_wait_times
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE yard_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE yard_checkpoints FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON yard_checkpoints;
CREATE POLICY tenant_isolation ON yard_checkpoints
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

-- ---- Transportation / logistics ----
ALTER TABLE carriers ENABLE ROW LEVEL SECURITY;
ALTER TABLE carriers FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON carriers;
CREATE POLICY tenant_isolation ON carriers
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE drivers ENABLE ROW LEVEL SECURITY;
ALTER TABLE drivers FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON drivers;
CREATE POLICY tenant_isolation ON drivers
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE shipments ENABLE ROW LEVEL SECURITY;
ALTER TABLE shipments FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON shipments;
CREATE POLICY tenant_isolation ON shipments
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE routes ENABLE ROW LEVEL SECURITY;
ALTER TABLE routes FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON routes;
CREATE POLICY tenant_isolation ON routes
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE load_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE load_plans FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON load_plans;
CREATE POLICY tenant_isolation ON load_plans
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE freight_charges ENABLE ROW LEVEL SECURITY;
ALTER TABLE freight_charges FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON freight_charges;
CREATE POLICY tenant_isolation ON freight_charges
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE dock_appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE dock_appointments FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON dock_appointments;
CREATE POLICY tenant_isolation ON dock_appointments
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE truck_asset_correlations ENABLE ROW LEVEL SECURITY;
ALTER TABLE truck_asset_correlations FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON truck_asset_correlations;
CREATE POLICY tenant_isolation ON truck_asset_correlations
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE load_quality_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE load_quality_logs FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON load_quality_logs;
CREATE POLICY tenant_isolation ON load_quality_logs
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

-- ---- Kanban / task management ----
ALTER TABLE task_boards ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_boards FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON task_boards;
CREATE POLICY tenant_isolation ON task_boards
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE task_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_rules FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON task_rules;
CREATE POLICY tenant_isolation ON task_rules
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE actionable_registries ENABLE ROW LEVEL SECURITY;
ALTER TABLE actionable_registries FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON actionable_registries;
CREATE POLICY tenant_isolation ON actionable_registries
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

-- ---- Correlation / analysis ----
ALTER TABLE data_correlations ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_correlations FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON data_correlations;
CREATE POLICY tenant_isolation ON data_correlations
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE analysis_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_sessions FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON analysis_sessions;
CREATE POLICY tenant_isolation ON analysis_sessions
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE intake_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE intake_items FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON intake_items;
CREATE POLICY tenant_isolation ON intake_items
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);


-- =============================================================================
-- PERMISSIVE RLS (6 tables): organization_id IS NULLABLE
--
-- NULL means "global / cross-tenant" (admin tooling, system audit, etc.).
-- Policy lets NULL rows be visible to everyone; non-NULL rows are
-- restricted to their organization.
-- =============================================================================

ALTER TABLE geotab_trips ENABLE ROW LEVEL SECURITY;
ALTER TABLE geotab_trips FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON geotab_trips;
CREATE POLICY tenant_isolation ON geotab_trips
  FOR ALL
  USING      (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE geotab_diagnostics ENABLE ROW LEVEL SECURITY;
ALTER TABLE geotab_diagnostics FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON geotab_diagnostics;
CREATE POLICY tenant_isolation ON geotab_diagnostics
  FOR ALL
  USING      (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE geotab_exceptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE geotab_exceptions FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON geotab_exceptions;
CREATE POLICY tenant_isolation ON geotab_exceptions
  FOR ALL
  USING      (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON audit_logs;
CREATE POLICY tenant_isolation ON audit_logs
  FOR ALL
  USING      (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE data_processing_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_processing_records FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON data_processing_records;
CREATE POLICY tenant_isolation ON data_processing_records
  FOR ALL
  USING      (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

ALTER TABLE integration_configurations ENABLE ROW LEVEL SECURITY;
ALTER TABLE integration_configurations FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON integration_configurations;
CREATE POLICY tenant_isolation ON integration_configurations
  FOR ALL
  USING      (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id IS NULL
              OR organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);


-- =============================================================================
-- EXPLICITLY NOT under RLS:
--   * users    — login lookup by email must succeed pre-authentication
--   * api_keys — API-key auth lookup by hash must succeed pre-authentication
--
-- Application-layer enforcement on tenant-scoped endpoints still applies.
-- Follow-up could re-enable RLS here via SECURITY DEFINER functions for
-- the two auth lookups.
-- =============================================================================

COMMIT;

-- End of migration 011.
