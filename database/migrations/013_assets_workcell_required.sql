-- Task 7: reconcile assets.workcell_id with the required ORM relationship.
-- Preserve legacy rows by assigning them to a tenant-owned fallback workcell.

INSERT INTO workcells (organization_id, name, description)
SELECT DISTINCT a.organization_id, 'Unassigned', 'Created during workcell constraint migration'
FROM assets a
WHERE a.workcell_id IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM workcells w
      WHERE w.organization_id = a.organization_id
        AND w.name = 'Unassigned'
  );

UPDATE assets a
SET workcell_id = w.id
FROM workcells w
WHERE a.workcell_id IS NULL
  AND w.organization_id = a.organization_id
  AND w.name = 'Unassigned';

ALTER TABLE assets
    ALTER COLUMN workcell_id SET NOT NULL;

ALTER TABLE assets
    DROP CONSTRAINT IF EXISTS assets_workcell_id_fkey;

ALTER TABLE assets
    ADD CONSTRAINT assets_workcell_id_fkey
    FOREIGN KEY (workcell_id) REFERENCES workcells(id) ON DELETE RESTRICT;
