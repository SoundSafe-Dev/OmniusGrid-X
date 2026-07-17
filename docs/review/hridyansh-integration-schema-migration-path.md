# Integration Schema Migration Path

This branch uses ordered SQL files in `database/migrations/` as the migration
source of truth. There is no Alembic revision chain for the integration branch
schema additions yet, so reviewers should validate the SQL migration order and
the ORM contract together.

## Migration Order

Run migrations in filename order:

1. `011_tenant_isolation_rls.sql`
   - Enables tenant RLS for existing tenant-owned application tables.
   - Adds tenant-session policy assumptions used by the middleware tests.
2. `012_export_templates.sql`
   - Adds `export_templates`, `scheduled_exports`, and
     `export_delivery_jobs`.
   - Uses tenant RLS, JSONB configuration fields, durable delivery jobs, and
     explicit FK delete behavior for tenant cleanup.
3. `013_assets_workcell_required.sql`
   - Backfills and enforces asset workcell ownership.
4. `014_compliance_tenant_isolation.sql`
   - Adds nullable `organization_id` columns and RLS policies to compliance
     tables that predate tenant ownership.
   - This is intentionally an intermediate migration so existing rows can be
     reconciled before the NOT NULL enforcement.
5. `015_compliance_report_jobs.sql`
   - Adds durable compliance report jobs and reconciles schemas that were
     created from ORM metadata before the migration existed.
6. `016_finalize_compliance_tenant_ownership.sql`
   - Enforces non-null tenant ownership for compliance tables after the data
     cleanup runbook has been completed.
   - Required runbook:
     `docs/deployment/runbooks/compliance-tenant-data-cleanup.md`.
7. `017_scheduled_compliance_reports.sql`
   - Adds scheduled compliance reports and links generated jobs back to their
     schedule with `ON DELETE SET NULL`.
8. `018_error_events.sql`
   - Adds aggregated error triage tables with status constraints and hourly
     occurrence buckets.

## Model-to-Migration Map

| ORM surface | Migration source | Contract notes |
| --- | --- | --- |
| Native UUID helpers and `Telemetry.meta_data` mapped to `metadata` | Existing base schema plus tenant tests | Keeps ORM-created test schemas aligned with Postgres UUID columns and reserved SQLAlchemy names. |
| `ExportTemplate` | `012_export_templates.sql` | JSONB `columns`/`filters`, unique `(organization_id, name)`, tenant cascade, nullable creator with `ON DELETE SET NULL`. |
| `ScheduledExport` | `012_export_templates.sql` | JSONB `recipients`, daily/weekly/monthly frequency check, tenant/template cascade, nullable creator with `ON DELETE SET NULL`. |
| `ExportDeliveryJob` | `012_export_templates.sql` | Unique `(schedule_id, scheduled_for)`, tenant/schedule/template cascade, nullable requester with `ON DELETE SET NULL`. |
| `SecurityAsset`, `VendorRiskAssessment` | `014_compliance_tenant_isolation.sql`, `016_finalize_compliance_tenant_ownership.sql` | Final branch contract is non-null `organization_id`; `014` is only the transitional backfill state. |
| `ComplianceReportJob` | `015_compliance_report_jobs.sql`, `017_scheduled_compliance_reports.sql` | JSONB recipients, report/delivery checks, tenant cascade, requester and schedule `ON DELETE SET NULL`. |
| `ScheduledComplianceReport` | `017_scheduled_compliance_reports.sql` | Frequency/status checks, JSONB recipients, tenant/requester FK behavior. |
| `ErrorEvent`, `ErrorEventBucket` | `018_error_events.sql` | Error status check, nullable status changer with `ON DELETE SET NULL`, bucket cascade by fingerprint. |

## Verification

Focused checks:

```bash
cd backend
python -m pytest -q tests/test_schema_migration_contract.py
python -m pytest -q tests/test_compliance_report_migration.py tests/test_compliance_tenant_migration.py tests/test_assets_workcell_migration.py
```

General review checks:

```bash
cd backend
python -m compileall -q app/db/models.py tests/test_schema_migration_contract.py
git diff --check
```

If this branch is later converted to Alembic, generate revisions from the SQL
files above rather than from current metadata alone. The SQL migrations include
RLS policies, cleanup sequencing, and upgrade reconciliation logic that
`Base.metadata.create_all()` cannot express.
