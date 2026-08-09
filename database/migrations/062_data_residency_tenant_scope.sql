-- 062: data_residency_tags gets an owner (FS-433)
--
-- THE TABLE HAD NO TENANT COLUMN AND NO RLS. Every organisation's residency tags sat in
-- one pool with nothing recording who they belonged to, behind six endpoints:
--
--   POST   /data-residency/tag                      require_admin
--   DELETE /data-residency/tag/{table}/{record_id}  require_admin
--   POST   /data-residency/validate                 require_admin
--   GET    /data-residency/tag/{table}/{record_id}  any authenticated user
--   GET    /data-residency/tags                     any authenticated user
--   GET    /data-residency/summary                  any authenticated user
--
-- `require_admin` is a PER-ORGANISATION admin. That is the entire argument FS-311 records
-- for why eight data-retention routes are dark — "a per-org admin would let one tenant
-- purge another's data" — and it applies here exactly, unenforced. So org A's admin could
-- delete org B's residency tags, and any authenticated user could enumerate every tenant's
-- tagged record ids together with the user ids that tagged them.
--
-- The aggregates were worse than a leak. `/summary` and `/validate` counted every tenant's
-- rows and returned the total as the caller's own compliance position — a number an
-- auditor is meant to rely on, computed over data the caller does not own.
--
-- BACKFILL VIA `tagged_by`. Each tag records the user who created it, and a user belongs to
-- exactly one organisation, so ownership is recoverable rather than guessed. Rows whose
-- `tagged_by` is null or names a deleted user cannot be attributed and are DELETED, not
-- assigned to an arbitrary organisation: a residency tag on the wrong tenant is worse than
-- a missing one, because the endpoints above would then report it as that tenant's
-- compliance evidence.

BEGIN;

-- UUID, matching `organizations.id`. `tagged_by` is varchar(36) in the ORM but the real
-- column is uuid: migration 032 converted the legacy varchar org columns, and 033's policy
-- quals cast with `::uuid` precisely because of that. A varchar column here would fail the
-- foreign key outright — "Key columns are of incompatible types" — which is how this was
-- caught rather than shipped.
ALTER TABLE data_residency_tags
  ADD COLUMN IF NOT EXISTS organization_id UUID;

UPDATE data_residency_tags t
   SET organization_id = u.organization_id
  FROM users u
 WHERE t.tagged_by = u.id
   AND t.organization_id IS NULL;

-- Unattributable rows. See the note above on why these go rather than being assigned.
DELETE FROM data_residency_tags WHERE organization_id IS NULL;

ALTER TABLE data_residency_tags
  ALTER COLUMN organization_id SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'fk_data_residency_tags_organization'
  ) THEN
    ALTER TABLE data_residency_tags
      ADD CONSTRAINT fk_data_residency_tags_organization
      FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
  END IF;
END $$;

-- One tag per (org, table, record). Without the organisation in the key, two tenants
-- tagging the same record id in the same table collided — and `record_id` is a UUID from
-- a tenant-scoped table, so a collision means one tenant's tag silently became the other's.
DROP INDEX IF EXISTS ix_data_residency_tags_table_record;
CREATE UNIQUE INDEX IF NOT EXISTS uq_data_residency_tags_org_table_record
  ON data_residency_tags (organization_id, table_name, record_id);

CREATE INDEX IF NOT EXISTS ix_data_residency_tags_organization
  ON data_residency_tags (organization_id);

ALTER TABLE data_residency_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_residency_tags FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON data_residency_tags;
CREATE POLICY tenant_isolation ON data_residency_tags
  FOR ALL
  USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
  WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);

COMMIT;
