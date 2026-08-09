-- 057_edge_agent_status_rls.sql
--
-- Row-level security for `edge_agent_status` — the third of the four gaps
-- `test_every_tenant_table_has_a_policy.py` recorded, and the one whose baseline entry named
-- the precondition most precisely:
--
--   "REAL GAP. Written by the ingestion worker, which binds the tenant GUC per message — so a
--    policy would probably work, but the heartbeat path has to be verified first: it runs on
--    AsyncSessionLocal and a FORCE policy would silently drop every write."
--
-- Verifying the heartbeat path found something worse than an unbound session. **The heartbeat
-- never wrote `organization_id` at all** — the row was created with an agent_id and nothing
-- else — while both read endpoints filter on that column. NULL never equals a uuid, so
-- `GET /api/v1/edge/fleet` returned `[]` for every tenant in every deployment since the endpoint
-- was written, and `/admin/collectors` showed an empty fleet however many agents were
-- heartbeating. The filter was not the mistake: it was added as a security fix for a genuinely
-- unscoped read. It scoped a read against a column the write path never populated, and turned
-- a leak into a permanent emptiness that nothing failed on.
--
-- ATTRIBUTING THE ROW REQUIRED THE AGENT TO HAVE A TENANT, which it did not. It now comes from
-- the certificate: enrolment decides the organisation server-side (explicit setting, else the
-- single organisation when that is unambiguous, else refuse) and the CA writes it into the
-- subject's O. That required fixing the CA too — `sign_csr` copied the CSR's subject wholesale
-- and validated only the CN, so reading a tenant out of that subject would have let every agent
-- name its own tenant and have the CA notarise it. The subject is now built server-side.
--
-- UNATTRIBUTED ROWS ARE DELETED, NOT LEFT. Once the policy is on, a row with a NULL
-- organization_id can be read by no tenant and updated by no tenant — and worse, it would make
-- its agent permanently broken: the agent's next heartbeat cannot see the row through the
-- policy, tries to INSERT, and hits the primary key. Deleting them is what makes the upgrade
-- self-healing; the next heartbeat recreates each row correctly attributed. Nothing is lost
-- that a 30-second heartbeat does not restore.
--
-- THE TRANSITION IS BOUNDED BY THE CERTIFICATE TTL. An agent holding a pre-existing certificate
-- has no organisation in it, so its heartbeat is refused with a 409 naming the remedy rather
-- than failing the policy check with a 500. Agent certificates are issued for
-- EDGE_CERT_TTL_DAYS (30), so every agent re-enrols within one lifetime and the window closes
-- itself.
--
-- FORCE, matching every other RLS table here: without it the owner bypasses the policy, and the
-- application connects as the owner in several deployments.
--
-- `organization_id` is VARCHAR(36) on this table (023_edge_fleet.sql), so the comparison is
-- text-to-text and needs NO ::uuid cast — unlike 056, whose tables declare a real UUID column.
-- 056 got that backwards on its first run and failed the whole chain with
-- `operator does not exist: uuid = text`. The DDL is the authority on a column's type.
--
-- Idempotent: the DELETE is a no-op on a second run, ENABLE/FORCE are repeatable, and
-- DROP POLICY IF EXISTS precedes CREATE.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'edge_agent_status'
      AND column_name = 'organization_id'
  ) THEN
    DELETE FROM edge_agent_status WHERE organization_id IS NULL;

    ALTER TABLE edge_agent_status ENABLE ROW LEVEL SECURITY;
    ALTER TABLE edge_agent_status FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON edge_agent_status;
    CREATE POLICY tenant_isolation ON edge_agent_status FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), ''))
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), ''));
  END IF;
END $$;
