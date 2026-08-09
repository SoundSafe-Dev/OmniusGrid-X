-- 051_fleet_logistics_rls.sql
--
-- Row-level security for the four fleet/maintenance tables that had none.
--
-- geofence_zones, geofence_alerts, maintenance_schedules and repair_orders all
-- carry organization_id, and all four were outside RLS entirely. Combined with
-- handlers on `get_db`, that left tenant isolation with NO layer at all: no
-- filter in the application, no policy in the database. Confirmed against a real
-- database before the fix -- the zone list returned every tenant's zones, and
-- fetch-by-id returned another tenant's zone outright.
--
-- The application layer is already fixed (every handler moved to get_tenant_db
-- and every query wrapped in `_scope`). This is the second layer, the one
-- app/core/tenant.py describes as "defense in depth so that even a query that
-- forgets where(organization_id == ...) cannot leak data across tenants". A
-- table with no policy is also invisible to the RLS-based isolation tests, so
-- the absence quietly removed these four from the suite meant to cover them.
--
-- NO ::uuid CAST, unlike 011/033. organization_id is `character varying` on all
-- four of these tables (it is `uuid` on assets, carriers, shipments, ...), so the
-- policy compares text to the text GUC. Casting would raise on every row.
-- `_scope` matches this by comparing against str(org_id).
--
-- FORCE is set, matching every other RLS table here: without it the table owner
-- bypasses the policy, which makes `relrowsecurity = true` misleading — it reads
-- as protected while the application's own connection is exempt.
--
-- Rows with a NULL organization_id become invisible to every tenant. That is the
-- intended reading: a row attributed to no organization belongs to none of them,
-- and surfacing it to everyone is how this class of bug looks in the first place.
--
-- SEEDER NOTE: backend/scripts/seed_demo_data.py writes these tables and sets no
-- tenant GUC, so it cannot populate them through a FORCE policy. This is not a
-- regression introduced here — it already writes `assets`, which has had ENABLE +
-- FORCE since migration 011, and it defaults to SQLite (where RLS does not
-- exist), which is how it runs today.
--
-- Idempotent: DROP POLICY IF EXISTS before CREATE, ENABLE/FORCE are repeatable,
-- and each table is guarded so the migration is safe where one is absent.

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'geofence_zones', 'geofence_alerts', 'maintenance_schedules', 'repair_orders'
  ] LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public' AND table_name = t
        AND column_name = 'organization_id'
    ) THEN
      EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY', t);
      EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
      EXECUTE format(
        'CREATE POLICY tenant_isolation ON %I FOR ALL '
        'USING      (organization_id = NULLIF(current_setting(''app.current_org_id'', true), '''')) '
        'WITH CHECK (organization_id = NULLIF(current_setting(''app.current_org_id'', true), ''''))',
        t
      );
    END IF;
  END LOOP;
END $$;
