-- 046_alarms_organization_id_rls.sql
--
-- Give `alarms` its own organization_id and RLS policy (FS-217).
--
-- WHY: `alarms` was never tenant-scoped at the database level. It is absent from
-- 011 and 033, and the table had no organization_id — tenancy existed only if a
-- query remembered to join `assets`. Five of the six endpoints in
-- app/api/alarms.py did not, so org B could read, acknowledge, clear and
-- bulk-acknowledge org A's alarms (FS-216 fixed the queries; this makes the
-- database enforce it too).
--
-- The distinction matters. On `assets`, a query that forgets its predicate returns
-- zero rows for the wrong tenant — the failure is safe. On `alarms` a forgotten
-- predicate returned EVERY tenant's rows. After this migration a forgotten
-- predicate is safe here too, so the next unscoped alarm query is a bug that
-- leaks nothing rather than a breach.
--
-- `alarms` is a TimescaleDB hypertable with PRIMARY KEY (id, occurred_at).
-- ALTER TABLE ADD COLUMN and RLS both apply to the hypertable and propagate to
-- its chunks; the policy is therefore declared once on the parent.
--
-- Idempotent: every step is guarded on the column/index/policy not already
-- existing, so re-running is a no-op.

-- ---------------------------------------------------------------------------
-- 1. Column, backfilled from the owning asset BEFORE it is made NOT NULL.
-- ---------------------------------------------------------------------------
-- alarms.asset_id is NOT NULL with an FK to assets, so every existing row has an
-- owning asset and the backfill is total — no fallback needed and no row can be
-- left NULL. That is why NOT NULL is safe to set unconditionally below.
DO $$
BEGIN
  IF to_regclass('public.alarms') IS NOT NULL
     AND NOT EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='public' AND table_name='alarms'
         AND column_name='organization_id'
     )
  THEN
    ALTER TABLE alarms ADD COLUMN organization_id UUID;

    UPDATE alarms a
       SET organization_id = s.organization_id
      FROM assets s
     WHERE a.asset_id = s.id
       AND a.organization_id IS NULL;

    -- Defensive: if anything were still NULL the NOT NULL below would fail loudly
    -- rather than silently leaving unscoped rows. Report instead of guessing.
    IF EXISTS (SELECT 1 FROM alarms WHERE organization_id IS NULL) THEN
      RAISE EXCEPTION
        'alarms.organization_id backfill incomplete: % row(s) have no owning asset',
        (SELECT count(*) FROM alarms WHERE organization_id IS NULL);
    END IF;

    ALTER TABLE alarms ALTER COLUMN organization_id SET NOT NULL;

    ALTER TABLE alarms
      ADD CONSTRAINT alarms_organization_id_fkey
      FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Index for the tenant-scoped reads the API actually issues.
-- ---------------------------------------------------------------------------
-- Every endpoint filters by organization and orders by occurred_at DESC (the
-- list endpoint additionally defaults to the last 24h), so the composite in that
-- order serves both the filter and the sort. Mirrors migration 043's approach.
CREATE INDEX IF NOT EXISTS idx_alarms_org_occurred
  ON alarms (organization_id, occurred_at DESC);

-- Active-alarm lookups are the dashboard's hot path.
CREATE INDEX IF NOT EXISTS idx_alarms_org_active
  ON alarms (organization_id, is_active, is_acknowledged);

-- ---------------------------------------------------------------------------
-- 3. RLS, matching the policy shape used by every other tenant table.
-- ---------------------------------------------------------------------------
-- FORCE is required: without it the table owner (the application role in most
-- deployments) bypasses the policy entirely, which is the exact gap that made
-- the dashboard's `get_db` bug survivable on `assets` but invisible here.
--
-- The ingestion worker already sets app.current_org_id on the session that
-- writes alarms (app/workers/ingestion.py:208), so WITH CHECK is satisfied on
-- the write path. Any writer that does NOT set the GUC will now fail loudly
-- instead of writing an unscoped row.
DO $$
BEGIN
  IF to_regclass('public.alarms') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='public' AND table_name='alarms'
         AND column_name='organization_id'
     )
  THEN
    ALTER TABLE alarms ENABLE ROW LEVEL SECURITY;
    ALTER TABLE alarms FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON alarms;
    CREATE POLICY tenant_isolation ON alarms
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;
