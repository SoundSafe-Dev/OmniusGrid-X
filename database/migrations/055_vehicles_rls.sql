-- 055_vehicles_rls.sql
--
-- Row-level security for `vehicles`, the one fleet table that still had none.
--
-- HOW THE GAP HAPPENED. Migration 011 covered the core tables; 033 extended that; 051 was
-- written for "the four fleet/maintenance tables that had none" and named them explicitly
-- (geofence_zones, geofence_alerts, maintenance_schedules, repair_orders). `vehicles` arrived
-- in 025 — too late for 011/033, and not on 051's list. Twelve of its thirteen sibling
-- logistics tables are covered; this one fell between two migrations.
--
-- WHY IT MATTERED, MEASURED RATHER THAN ASSUMED. Fourteen create handlers were reading
-- `organization_id` out of the request body, letting a caller name the tenant they wrote to.
-- On the thirteen RLS-covered tables the database refused the write — a FOR ALL policy's
-- USING clause acts as the INSERT's WITH CHECK — so the caller got a 500: bad error handling,
-- not a breach. On `vehicles` the write SUCCEEDED, because nothing stood between the body and
-- the row. Same defect, same three files, and the only one that shipped was the one whose
-- table had no second layer.
--
-- The handlers are fixed (every one now takes the tenant from `get_tenant_org_id`, guarded by
-- tests/test_no_handler_takes_its_tenant_from_the_body.py). This is the second layer, in the
-- order migration 051 insists on: application first, policy after. Verified before writing
-- this — all seven functions that query `Vehicle` across app/api and app/services already run
-- on `get_tenant_db`, so no read is about to start returning zero rows.
--
-- NO ::uuid CAST. `vehicles.organization_id` is `character varying(36)` (logistics_models.py),
-- as on the four tables in 051 — not `uuid` as on assets/carriers/shipments. Casting would
-- raise on every row. The policy compares text to the text GUC.
--
-- FORCE, matching every other RLS table here. Without it the table owner bypasses the policy,
-- which makes `relrowsecurity = true` actively misleading: it reads as protected while the
-- application's own connection is exempt.
--
-- Rows with a NULL organization_id become invisible to every tenant. That is the intended
-- reading, and it is also why the handler fix matters independently: `payload.get(...)`
-- returned None for an absent field, and this policy turns such a row from "belongs to
-- everyone" into "belongs to no one" — better, but still a row nobody asked for.
--
-- Idempotent: ENABLE/FORCE are repeatable, DROP POLICY IF EXISTS precedes CREATE, and the
-- table is guarded so this is safe on a database where `vehicles` is absent.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'vehicles'
      AND column_name = 'organization_id'
  ) THEN
    ALTER TABLE vehicles ENABLE ROW LEVEL SECURITY;
    ALTER TABLE vehicles FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON vehicles;
    CREATE POLICY tenant_isolation ON vehicles FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), ''))
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), ''));
  END IF;
END $$;

COMMENT ON TABLE vehicles IS
  'Fleet vehicles. RLS + FORCE since migration 055; organization_id is varchar, so the policy
   compares text to app.current_org_id without a cast (see 051 for the same shape).';
