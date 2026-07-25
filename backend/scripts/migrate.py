#!/usr/bin/env python
"""Incremental SQL migration runner (FS-22).

The repo previously applied database/migrations/*.sql only through Postgres'
docker-entrypoint-initdb.d, which runs once on an EMPTY data volume — there was
no way to apply a new migration to an existing database (and the Makefile/CI
`alembic upgrade head` referenced an alembic setup that does not exist).

This runner tracks applied migrations in a `schema_migrations` table and applies
only the pending ones, per-statement in autocommit mode (some migrations use
TimescaleDB continuous aggregates / ALTER SYSTEM, which cannot run inside a
transaction block), in sorted filename order. Filenames are the version key, so
duplicate numeric prefixes (004_a / 004_b) are still distinct, ordered
deterministically by the full name.

Usage (from backend/):
    python scripts/migrate.py                # apply all pending
    python scripts/migrate.py --status       # show applied / pending
    python scripts/migrate.py --baseline     # mark all as applied WITHOUT running
                                             # (for a DB already built via initdb)
    python scripts/migrate.py --dir PATH     # override migrations dir

Postgres only — SQLite/dev builds the schema from ORM metadata via init_db().

FS-56 adoption (existing databases): 12 files were fixed in place because they
could never have applied as written (004/005/005-kanban/006/008/009-audit/
009-floor/010/011/020/021/030). A previously-baselined database refuses on
checksum drift — run `migrate.py --rebaseline-drifted` once, then `migrate.py`
to apply the pending convergence migrations (032 varchar->uuid, 033 RLS
backfill).
"""

import argparse
import hashlib
import sys
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"

# Migrations that CONVERGE existing schemas (as opposed to defining them) —
# excluded from --baseline so adopted databases still run them.
CONVERGENCE_PREFIXES = ("032_", "033_")

# DEMO/SAMPLE DATA masquerading as schema migrations (FS-203). These four INSERT
# fixture rows — test kanban cards, sample registries, a "dev floor" of assets —
# and were in the production chain, so every real deployment silently received
# fake operational data. They are skipped unless explicitly requested.
#
# They are NOT deleted: databases that already ran them have the versions
# recorded, and removing the files would look like checksum/history tampering.
# Gating is the reversible fix; `backend/scripts/seed_demo_data.py` is the
# sanctioned way to get demo data now.
DEV_FIXTURE_PREFIXES = (
    "005_populate_test_kanban_data",
    "006_populate_extended_kanban_data",
    "008_populate_actionable_registries",
    "009_dev_floor_sample_data",
)


def _is_dev_fixture(name: str) -> bool:
    return name.startswith(DEV_FIXTURE_PREFIXES)


def _pg_dsn() -> str:
    """Return a psycopg2 DSN from DATABASE_URL (env first, app settings second).

    Preferring the env var keeps this script runnable in slim CI environments
    without the app's full dependency tree.
    """
    import os
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app.core.config import settings
        url = settings.DATABASE_URL
    # Strip SQLAlchemy driver suffixes: postgresql+asyncpg:// -> postgresql://
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    if url.startswith("sqlite"):
        raise SystemExit(
            "migrate.py targets Postgres; SQLite dev builds schema via init_db(). "
            "Set DATABASE_URL to a postgresql:// URL."
        )
    return url


def _migration_files(mdir: Path):
    return sorted(p for p in mdir.glob("*.sql"))


def _ensure_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     TEXT PRIMARY KEY,
            checksum    TEXT NOT NULL,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _applied(cur) -> dict:
    cur.execute("SELECT version, checksum FROM schema_migrations")
    return dict(cur.fetchall())


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply pending SQL migrations.")
    ap.add_argument("--status", action="store_true", help="show applied/pending and exit")
    ap.add_argument("--baseline", action="store_true", help="record all as applied without running")
    ap.add_argument(
        "--rebaseline",
        metavar="FILE",
        nargs="+",
        help="re-record the stored checksum for already-applied migration "
             "file(s) that were deliberately edited (e.g. the FS-56 fixes). "
             "Does NOT run them — pair with the convergence migrations (032+). "
             "Use --rebaseline-drifted to adopt every drifted file at once.",
    )
    ap.add_argument(
        "--rebaseline-drifted",
        action="store_true",
        help="re-record checksums for ALL applied files whose content drifted "
             "(the FS-56 batch edited 12 files; see --status for the list)",
    )
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="migrations directory")
    ap.add_argument(
        "--with-dev-fixtures",
        action="store_true",
        help="also apply the demo/sample-data migrations (005/006/008/009 "
             "populate_*). Off by default: they insert fake operational rows.",
    )
    args = ap.parse_args()

    mdir = Path(args.dir)
    files = _migration_files(mdir)
    if not files:
        # Fail LOUDLY: an empty/missing migrations dir almost always means a
        # wrong --dir or a container without the repo tree mounted — exiting 0
        # here once let a prod bringup "succeed" with zero tables.
        print(f"ERROR: no .sql migrations found in {mdir} — wrong --dir or "
              "missing mount?", file=sys.stderr)
        return 1

    import psycopg2
    import sqlparse

    # Autocommit + per-statement execution: some migrations use TimescaleDB
    # continuous aggregates / CREATE INDEX CONCURRENTLY, which cannot run inside
    # a transaction block (same approach psql initdb and conftest.py use).
    conn = psycopg2.connect(_pg_dsn())
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            _ensure_table(cur)
            applied = _applied(cur)

        if args.status:
            print(f"{len(applied)} applied, {len(files) - len(applied)} pending:")
            for f in files:
                mark = "APPLIED" if f.name in applied else "pending"
                drift = ""
                if f.name in applied and applied[f.name] != _checksum(f):
                    drift = "  !! checksum drift"
                print(f"  [{mark}] {f.name}{drift}")
            return 0

        if args.rebaseline or args.rebaseline_drifted:
            if args.rebaseline_drifted:
                targets = [
                    f for f in files
                    if f.name in applied and applied[f.name] != _checksum(f)
                ]
                if not targets:
                    print("no checksum drift found; nothing to rebaseline")
                    return 0
            else:
                targets = [mdir / name for name in args.rebaseline]
            for target in targets:
                if not target.exists():
                    print(f"ERROR: {target} does not exist", file=sys.stderr)
                    return 1
                if target.name not in applied:
                    print(
                        f"ERROR: {target.name} is not recorded as applied — nothing "
                        "to rebaseline (a pending file just runs normally).",
                        file=sys.stderr,
                    )
                    return 1
            with conn.cursor() as cur:
                for target in targets:
                    cur.execute(
                        "UPDATE schema_migrations SET checksum = %s WHERE version = %s",
                        (_checksum(target), target.name),
                    )
                    print(f"rebaselined {target.name} (checksum re-recorded; file NOT run)")
            return 0

        if args.baseline:
            # Convergence migrations must RUN on adopted databases — that is
            # their whole purpose (an adopted create_all DB is exactly the
            # varchar-era schema 032 converts). Recording them here would
            # silently skip the conversion forever.
            skipped = [f.name for f in files if f.name.startswith(CONVERGENCE_PREFIXES)]
            with conn.cursor() as cur:
                for f in files:
                    if f.name in applied or f.name.startswith(CONVERGENCE_PREFIXES):
                        continue
                    cur.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (f.name, _checksum(f)),
                    )
            print(f"baselined {len(files) - len(applied) - len(skipped)} migration(s) as applied (not run)")
            if skipped:
                print(f"NOT baselined (convergence migrations, run `migrate.py` to apply): {', '.join(skipped)}")
            return 0

        # Safety: an initdb-built database (docker-entrypoint-initdb.d already ran
        # the migrations, but schema_migrations is empty) must be BASELINED, not
        # migrated — re-running from 001 would execute destructive statements
        # (004_fix_kanban_tables DROPs task tables) against live data.
        if not applied:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'organizations')"
                )
                schema_exists = cur.fetchone()[0]
            if schema_exists:
                print(
                    "REFUSING to migrate: this database already has a schema "
                    "(organizations table exists) but no schema_migrations records — "
                    "it was likely built via initdb. Run `migrate.py --baseline` "
                    "first to adopt it, then re-run.",
                    file=sys.stderr,
                )
                return 1

        # Fail loudly on checksum drift: an already-applied migration whose file
        # content changed means fresh and existing databases would diverge.
        drifted = [
            f.name for f in files
            if f.name in applied and applied[f.name] != _checksum(f)
        ]
        if drifted:
            print(
                "REFUSING to migrate: applied migration(s) were edited after being "
                f"recorded (checksum drift): {', '.join(drifted)}. Add a NEW "
                "migration instead of editing an applied one.",
                file=sys.stderr,
            )
            return 1

        pending = [f for f in files if f.name not in applied]

        # Demo/sample-data fixtures are opt-in. Without this, a production
        # migrate run inserts fake kanban cards and a "dev floor" of assets.
        if not args.with_dev_fixtures:
            held = [f.name for f in pending if _is_dev_fixture(f.name)]
            pending = [f for f in pending if not _is_dev_fixture(f.name)]
            if held:
                print(
                    "SKIPPING demo-data fixtures (not schema): "
                    + ", ".join(held)
                    + "\n  These insert sample rows and are excluded from real "
                    "deployments. Use --with-dev-fixtures to apply them, or "
                    "backend/scripts/seed_demo_data.py for demo data."
                )

        if not pending:
            print("database is up to date; nothing to apply")
            return 0

        for f in pending:
            statements = [
                s for s in sqlparse.split(f.read_text())
                # comment-only "statements" strip to non-empty text but are an
                # empty query to the server — filter on comment-stripped form
                if sqlparse.format(s, strip_comments=True).strip()
            ]
            try:
                with conn.cursor() as cur:
                    for stmt in statements:
                        cur.execute(stmt)
                    cur.execute(
                        "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                        (f.name, _checksum(f)),
                    )
                print(f"  applied {f.name}")
            except Exception as e:  # noqa: BLE001
                print(f"  FAILED {f.name}: {e}", file=sys.stderr)
                return 1
        print(f"applied {len(pending)} migration(s)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
