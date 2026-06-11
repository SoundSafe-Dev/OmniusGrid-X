# Compliance Tenant Data Cleanup

Use this runbook after migration `014_compliance_tenant_isolation.sql` and before
`016_finalize_compliance_tenant_ownership.sql`.

Migration 014 automatically assigns ownership only when a security asset owner or
vendor assessor belongs to an organization. Any remaining rows are hidden by strict
RLS. Do not infer ownership from names or other weak signals.

## 1. Review unresolved rows

Run these queries with an authorized administrative database account:

```sql
SELECT
    sa.id,
    sa.asset_name,
    sa.asset_type,
    sa.owner_id,
    u.email AS owner_email,
    u.organization_id AS owner_organization_id
FROM security_assets AS sa
LEFT JOIN users AS u ON u.id = sa.owner_id
WHERE sa.organization_id IS NULL
ORDER BY sa.created_at, sa.id;

SELECT
    vra.id,
    vra.vendor_name,
    vra.assessor_id,
    u.email AS assessor_email,
    u.organization_id AS assessor_organization_id
FROM vendor_risk_assessments AS vra
LEFT JOIN users AS u ON u.id = vra.assessor_id
WHERE vra.organization_id IS NULL
ORDER BY vra.created_at, vra.id;
```

For each row, confirm ownership from an authoritative business record. Record the
row ID, decision, organization ID, reviewer, and review date outside the database.

## 2. Apply approved decisions

Assign a reviewed row:

```sql
UPDATE security_assets
SET organization_id = '<approved-organization-uuid>'
WHERE id = '<reviewed-row-uuid>'
  AND organization_id IS NULL;

UPDATE vendor_risk_assessments
SET organization_id = '<approved-organization-uuid>'
WHERE id = '<reviewed-row-uuid>'
  AND organization_id IS NULL;
```

Delete a row only when the reviewer confirms it is truly orphaned:

```sql
DELETE FROM security_assets
WHERE id = '<reviewed-orphan-uuid>'
  AND organization_id IS NULL;

DELETE FROM vendor_risk_assessments
WHERE id = '<reviewed-orphan-uuid>'
  AND organization_id IS NULL;
```

Use a transaction for each approved cleanup batch and verify affected row counts
before committing.

## 3. Verify and finalize

Both counts must be zero:

```sql
SELECT count(*) FROM security_assets WHERE organization_id IS NULL;
SELECT count(*) FROM vendor_risk_assessments WHERE organization_id IS NULL;
```

Back up the database, then apply migration 016. The migration aborts without making
changes if either table still contains unresolved rows.

Afterward, verify both columns report `is_nullable = 'NO'` and run the compliance
tenant-isolation integration tests.
