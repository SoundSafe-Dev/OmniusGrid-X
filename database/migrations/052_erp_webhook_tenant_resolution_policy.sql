-- 052_erp_webhook_tenant_resolution_policy.sql
--
-- Let the inbound ERP webhook receiver resolve its tenant, and nothing else.
--
-- THE BREAKAGE. `POST /api/v1/erp/webhooks/{erp_type}` rejected EVERY inbound
-- webhook with 404. integration_configurations is FORCE ROW LEVEL SECURITY with a
-- tenant policy keyed on app.current_org_id, and the receiver is an
-- unauthenticated vendor callback: there is no user to derive a tenant from, so no
-- GUC is set when the candidate lookup runs. The policy matched nothing, the
-- handler found no candidates, and answered "no active ERP integration for
-- '<erp_type>'". Verified against a real database.
--
-- WHY THE LOOKUP MUST CROSS ORGANISATIONS. The route is one shared path per vendor
-- with nothing in the URL or headers identifying the organisation. The tenant is
-- whoever holds the secret that verifies these exact bytes -- that is the design,
-- and it is the right one for a shared path, because the signature is the only
-- trustworthy evidence in the request. Resolving the tenant therefore requires
-- reading candidates from every organisation, before any tenant is known.
--
-- So this cannot be fixed by swapping get_db for get_tenant_db. The alternative --
-- putting the organisation in the URL -- would mean every vendor reconfiguring
-- their endpoint AND trusting a caller-supplied identifier to select whose secret
-- to check against, which is strictly worse.
--
-- WHAT THIS POLICY GRANTS, precisely:
--
--   * SELECT only. No INSERT, UPDATE or DELETE. The existing tenant_isolation
--     policy remains the only way to write.
--   * Only rows that are integration_type = 'erp' AND is_active. A dormant or
--     non-ERP integration is never visible through it.
--   * Only while app.erp_webhook_lookup = 'on'. The application sets that GUC
--     transaction-locally, immediately before the candidate query, and clears it
--     immediately after -- so it is off for the event INSERT that follows and for
--     every other code path in the process.
--
-- Postgres OR-s permissive policies, so this widens SELECT for that one flagged
-- moment and changes nothing otherwise. It needs no superuser and no BYPASSRLS
-- role, which matters: the application connects as a NOSUPERUSER NOBYPASSRLS role
-- on purpose, and `SET row_security = off` would have required giving that up.
--
-- RESIDUAL RISK, stated plainly: anything able to set this GUC on a session can
-- list active ERP integrations across tenants, including their `configuration`
-- JSON, which holds webhook secrets. That is the same trust boundary as the
-- database credentials themselves -- the flag is only settable by something already
-- connected as the application. It is narrowed as far as a table-level policy can
-- be; column-level restriction is not expressible in RLS.
--
-- Idempotent: DROP POLICY IF EXISTS before CREATE, and guarded so the migration is
-- safe where the table is absent.

DO $$
BEGIN
  IF to_regclass('public.integration_configurations') IS NOT NULL THEN
    DROP POLICY IF EXISTS webhook_tenant_resolution ON integration_configurations;
    CREATE POLICY webhook_tenant_resolution ON integration_configurations
      FOR SELECT
      USING (
        integration_type = 'erp'
        AND is_active
        AND NULLIF(current_setting('app.erp_webhook_lookup', true), '') = 'on'
      );
  END IF;
END $$;
