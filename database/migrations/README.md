# Migrations

Applied by `backend/scripts/migrate.py` in **sorted filename order**. The
filename — not the numeric prefix — is the version key recorded in
`schema_migrations`, along with a checksum.

```bash
cd backend
python scripts/migrate.py --status     # applied / pending
python scripts/migrate.py              # apply pending
```

Two consequences of keying on the full filename are worth knowing before you
touch anything in here:

- **Never edit an applied migration.** The runner refuses on checksum drift,
  because fresh and existing databases would otherwise diverge. Add a new one.
- **Never rename an applied migration.** A rename reads as a brand-new pending
  version, so it would *re-run* — and some of these are destructive
  (`004_fix_kanban_tables.sql` DROPs task tables). This is why the historical
  duplicate prefixes below are grandfathered rather than tidied up.

## Why 019 is missing

The sequence jumps 018 → 020. Nothing was lost: `019_erp_integration_tables`
existed on the `integration-erp` branch, and during convergence that branch's ERP
foundation was **superseded** by the canonical connector suite, which landed as
`020_erp_integration_tables.sql`. 019 was dropped deliberately rather than
merged. See `docs/review/fixed-sprints-integration-convergence.md` § Ownership.

Filling the gap with a placeholder would be worse than leaving it: it would imply
a migration that never applied anywhere. `test_migration_chain_hygiene.py` pins
019 as the one known gap, so a *new* gap — which would suggest an actually lost
file — fails.

## Duplicate prefixes (grandfathered)

Four prefixes carry two files each, all merge artifacts from the kanban era:

| Prefix | Files |
|--------|-------|
| 004 | `004_fix_kanban_tables.sql`, `004_query_optimization.sql` |
| 005 | `005_data_retention.sql`, `005_populate_test_kanban_data.sql` |
| 007 | `007_actionable_registries.sql`, `007_operator_kanban_assignments.sql` |
| 009 | `009_audit_logs.sql`, `009_dev_floor_sample_data.sql` |

They apply deterministically (full-filename sort), and renaming them would
re-run them — see above. `backend/scripts/check_migrations.py` grandfathers
exactly these four and **fails any new duplicate**; it runs as the blocking
`migration-hygiene` CI job.

## Demo-data migrations are NOT applied by default

Four migrations insert sample rows rather than defining schema:

- `005_populate_test_kanban_data.sql`
- `006_populate_extended_kanban_data.sql`
- `008_populate_actionable_registries.sql`
- `009_dev_floor_sample_data.sql`

They used to run everywhere, so real deployments received fake kanban cards,
sample registries and a made-up "dev floor" of assets. `migrate.py` now skips
them unless `--with-dev-fixtures` is passed. They are kept (not deleted) because
databases that already applied them have those versions recorded.

**For demo data, use `backend/scripts/seed_demo_data.py`** — it seeds every page
coherently and is idempotent.

## Conventions

- Pick the next free prefix; `check_migrations.py` enforces uniqueness.
- Make statements idempotent (`IF NOT EXISTS`, guarded `DO $$` blocks) so a
  partially-applied migration can be re-run.
- Schema and data belong in separate files; a data-only migration fails
  `test_migration_chain_hygiene.py`.
- `created_at` / `updated_at` need a **server** default
  (`DEFAULT NOW()`), not just an ORM-side one — a raw INSERT otherwise writes
  NULL and the row vanishes from time-ordered queries. See `044`/`045`, enforced
  by `test_schema_parity.py`.
- **A migration that uses an extension function must create the extension.** Never
  rely on it being present, and never rely on the test harness creating it —
  `tests/conftest.py` runs `CREATE EXTENSION IF NOT EXISTS pgcrypto` when it builds a
  container, which is why `009_audit_logs.sql` could call `digest()` for months with a
  green test suite while **every production audit insert failed**. The trigger raised
  `UndefinedFunctionError`, `app/services/audit.py` swallowed it by design ("never fail
  the audited operation"), and the audit trail was empty. Fixed by `059`; enforced by
  `test_schema_extensions_come_from_migrations.py`, which fails on any extension the
  harness creates and no migration does.
- Prefer proving the dependency over assuming it. `059` runs `digest()` in a guarded
  `DO $$` block after `CREATE EXTENSION` and raises if it is still unusable — a failed
  migration is a better outcome than a feature that quietly discards data.
