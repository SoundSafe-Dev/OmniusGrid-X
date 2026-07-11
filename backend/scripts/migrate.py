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
"""

import argparse
import hashlib
import sys
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"


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
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="migrations directory")
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

        if args.baseline:
            with conn.cursor() as cur:
                for f in files:
                    if f.name not in applied:
                        cur.execute(
                            "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                            (f.name, _checksum(f)),
                        )
            print(f"baselined {len(files) - len(applied)} migration(s) as applied (not run)")
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
        if not pending:
            print("database is up to date; nothing to apply")
            return 0

        for f in pending:
            statements = [s for s in sqlparse.split(f.read_text()) if s.strip()]
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
