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
- **Make statements idempotent** (`IF NOT EXISTS`, guarded `DO $$` blocks) so a
  partially-applied migration can be re-run. This is not a style preference: `migrate.py`
  runs in autocommit and executes one statement at a time, because continuous aggregates and
  `add_retention_policy` refuse a transaction block. A file that fails at statement 7 has
  **committed statements 1–6 and recorded no version**, so running it again is the only
  recovery there is. Wrapping the file in `BEGIN;`/`COMMIT;` is the other valid answer —
  seventeen migrations take it — but not for a file that creates a continuous aggregate.
  Enforced by `test_every_migration_can_be_rerun_realdb.py`, which applies the chain from
  empty and re-runs each file at its own point in it.
- Postgres has no `IF NOT EXISTS` for a **policy, trigger or constraint**. The idiom here is
  `DROP POLICY IF EXISTS x ON t;` before the `CREATE`, or `ADD CONSTRAINT` inside a guarded
  `DO $$ … IF NOT EXISTS … $$` block. Twenty-two files look non-idempotent to a text search
  for this reason; four actually are.

## The four migrations that cannot be re-run

Measured 2026-08-08 against `timescaledb:latest-pg15`:

| File | Statement that fails the retry |
|------|-------------------------------|
| `001_init.sql` | `CREATE TABLE organizations` — no `IF NOT EXISTS` |
| `002_continuous_aggregates.sql` | `CREATE MATERIALIZED VIEW … WITH (timescaledb.continuous)` |
| `004_query_optimization.sql` | two bare `CREATE INDEX` |
| `010_api_keys.sql` | `INSERT INTO permissions … VALUES` with no `ON CONFLICT` |

**Do not fix them.** Every existing database has applied all four, and editing an applied
migration is checksum drift — the runner then refuses to migrate at all until somebody runs
`--rebaseline-drifted`. A repair here takes deployed databases out of service and improves
nothing, because they will never be run again on a database that already has them. The list
is closed; the guard exists to keep a *new* migration off it.

If one of these does fail halfway on a fresh bringup, the recovery is to drop the database and
start again, not to re-run the file.
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
