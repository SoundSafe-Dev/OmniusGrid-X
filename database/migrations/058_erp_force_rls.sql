-- 058_erp_force_rls.sql
--
-- FORCE ROW LEVEL SECURITY on the five ERP tables that have had a policy since 020/033 and
-- have never had FORCE.
--
-- WHY THIS IS THE MORE DANGEROUS STATE, not a lesser one. Without FORCE the table OWNER bypasses
-- the policy entirely, and the application connects as the owner in several deployments. So
-- `relrowsecurity = true` reads as protected while the only connection that matters is exempt —
-- the question is answered, and answered wrongly. `app/api/erp_integrations.py` already records
-- what that cost: its background sync "appeared to work only because no ERP table has FORCE ROW
-- LEVEL SECURITY and the dev connection owns them", which is to say the tenant GUC it now sets
-- was never actually being tested.
--
-- WHAT WAS VERIFIED FIRST, because the policy-coverage baseline made each entry name its own
-- precondition and they were not the same:
--
--   * erp_sync_status / erp_entities / erp_correlations — written by `run_erp_sync`, which
--     opens its own session for a background task and sets `app.current_org_id` explicitly, and
--     by `correlate_synced_records`, which is handed that same session. One transaction, one
--     commit at the end, so the transaction-scoped GUC covers every statement.
--   * erp_data_mappings — written by the mapping routes, which run on `get_tenant_db`.
--   * erp_integration_events — appended from both the request path and the webhook path;
--     `erp_webhooks.py` sets the GUC after resolving the tenant from the integration record.
--
--   * The dynamics/oracle/SAP `*_data_extraction` services and `erp_database_replication` also
--     write these tables and take their session as a parameter — but NOTHING IMPORTS THEM.
--     ~1,800 lines reachable from no router, no worker and no test but one honesty check. They
--     are not a reason to leave FORCE off; if they are ever wired up, their caller supplies the
--     session and has to bind it, exactly like every other background writer here.
--
-- THE VERIFICATION RUN NEARLY DID NOT HAPPEN, and this header nearly claimed it did. The two
-- real-Postgres suites that exercise the sync path — test_erp_sync_e2e_realdb.py and
-- test_erp_platform_integration_realdb.py — SKIP IN FULL without live Dataverse credentials:
-- 29 of 54 tests, including every one that touches `run_erp_sync`. Running them and reading
-- "25 passed" would have confirmed this migration against a suite that never executed the code
-- the migration can break.
--
-- So test_erp_background_sync_under_force_realdb.py was written: the same path with the vendor
-- call stubbed, since the vendor call is the only part that needs credentials and is not the
-- part under test. It asserts FORCE is actually on (otherwise a successful write proves nothing
-- — the owner would bypass the policy exactly as before), then drives `run_erp_sync` and checks
-- the rows landed and are attributed. Controlled by deleting the `_set_tenant_guc` call: three
-- of its tests go red, which is the proof that the binding is what makes the writes succeed
-- rather than the ownership.
--
-- On SQLite none of this exists, so a green run there would also have proved nothing.
--
-- FORCE only. The policies from 020/033 are left exactly as they are: `FOR ALL USING (...)` with
-- no explicit WITH CHECK, which Postgres applies as the check for INSERT. Changing two things at
-- once would make a failure ambiguous about which one caused it.
--
-- Idempotent: FORCE is repeatable, and each table is guarded so this is safe where one is absent
-- or where RLS was never enabled on it.

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'erp_entities',
    'erp_sync_status',
    'erp_data_mappings',
    'erp_correlations',
    'erp_integration_events'
  ] LOOP
    IF EXISTS (
      SELECT 1 FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE n.nspname = 'public' AND c.relname = t AND c.relrowsecurity
    ) THEN
      EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    END IF;
  END LOOP;
END $$;
