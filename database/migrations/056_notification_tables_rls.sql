-- 056_notification_tables_rls.sql
--
-- Row-level security for `notification_subscriptions` and `notification_deliveries`.
--
-- WHY THESE TWO, AND WHY NOW. `test_every_tenant_table_has_a_policy.py` recorded six tables
-- carrying `organization_id` with no policy. Two are exempt by necessity (`users` and
-- `api_keys` are read *before* a tenant is known). These two were recorded as REAL GAPS whose
-- entry said what closing them required: "Handlers are already tenant-scoped. Closing it needs
-- a check of the dispatcher, which reads subscriptions from a background task with no request
-- behind it."
--
-- That check found four defects rather than a clean bill, all in the shape
-- `if org is not None: stmt = stmt.where(...)`:
--
--   * `list_subscriptions` and `delivery_log` skipped the filter entirely for a user whose
--     organisation was NULL, and returned every tenant's rows — the delivery log carries alarm
--     titles and detail text, which is the most specific operational information here;
--   * `delete_subscription` had NO organisation clause at all, so any authenticated user could
--     delete any tenant's subscription by id;
--   * `_load_rules` in the dispatcher had the same conditional filter, so a dispatch with no
--     organisation would have loaded every tenant's subscriptions and DELIVERED to all of them
--     — one tenant's alarm arriving at another's webhook. Latent: both callers pass an
--     organisation today.
--
-- All five handlers now depend on `get_tenant_org_id`, and every session — including the
-- dispatcher's two, which run from a background task — goes through `core.tenant.tenant_session`
-- so the GUC is bound and re-asserted per transaction. That is the precondition this migration
-- needed, and it is why the policy can go on now and could not before: a FORCEd policy over
-- unbound sessions would have emptied every read instead of protecting it.
--
-- ::uuid CAST, unlike 051 and 055. `organization_id` is a real `UUID` column on both tables
-- (022_notifications.sql declares `organization_id UUID REFERENCES organizations(id)`), so the
-- GUC — which is text — has to be cast to compare.
--
-- THE FIRST VERSION OF THIS FILE OMITTED THE CAST and the migration chain failed to build the
-- test schema at all: `operator does not exist: uuid = text`. That was my error, and instructive
-- about how: the ORM says `Column(UUIDString(), ...)`, which reads like a varchar and is the
-- reason 051's four tables and 055's `vehicles` genuinely are varchar. The DDL is the authority
-- on a column's type, not the model — a custom SQLAlchemy type can render as either. Loudly
-- wrong rather than quietly wrong, at least: a policy comparing incompatible types raises on
-- every row instead of silently matching none.
--
-- FORCE, matching every other RLS table here. Without it the table owner bypasses the policy,
-- and the application connects as the owner in several deployments, so `relrowsecurity = true`
-- would read as protected while the only connection that matters is exempt.
--
-- Rows with a NULL organization_id become invisible to every tenant. Deliberate: a delivery
-- attributed to no organisation belongs to none of them, and the dispatcher can no longer write
-- one — it refuses to dispatch without a tenant rather than recording an unattributed row.
--
-- Idempotent: ENABLE/FORCE are repeatable, DROP POLICY IF EXISTS precedes CREATE, and each
-- table is guarded so this is safe where one is absent.

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['notification_subscriptions', 'notification_deliveries'] LOOP
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
        'USING      (organization_id = NULLIF(current_setting(''app.current_org_id'', true), '''')::uuid) '
        'WITH CHECK (organization_id = NULLIF(current_setting(''app.current_org_id'', true), '''')::uuid)',
        t
      );
    END IF;
  END LOOP;
END $$;
