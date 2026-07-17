"""Schema-parity guard (FS-91): the ORM must match the MIGRATED database.

Why this exists: during the convergence the app was silently broken against any
migrations-built Postgres — ORM columns (users.department/priorities/...,
8 tables' ``meta_data``) were never added to the migration chain, so every
authenticated request 500'd in production-shaped databases while SQLite
``create_all`` (dev/tests) hid the drift entirely. Migrations 039/040 repaired
it by hand; this test makes the drift class un-shippable.

Runs against the session testcontainers TimescaleDB whose schema is built by
``scripts/migrate.py`` (the production path) in ``conftest._setup_schema``.
Skips cleanly where docker/testcontainers are unavailable (CI runs it).
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("testcontainers")

from app.db.models import Base  # noqa: E402


# -- intentional, reviewed exceptions ---------------------------------------
# (table, column) pairs the parity checks must not flag, each with a reason.
NULLABILITY_ALLOWLIST = {
    # ORM-nullable but NOT NULL in migration 036: every create path defaults it
    # to {} in code (command_executor / api), so inserts never send NULL.
    ("commands", "parameters"),
}

TYPE_ALLOWLIST: set[tuple[str, str]] = {
    # none currently — add (table, column) with a reason when a mismatch is
    # reviewed and accepted rather than fixed.
}


def _db_columns(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_name, is_nullable, column_default, udt_name "
                "FROM information_schema.columns WHERE table_schema = 'public'"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {
        (t, c): {"nullable": n == "YES", "default": d, "udt": u}
        for t, c, n, d, u in rows
    }


def _orm_type_category(col) -> str:
    from sqlalchemy.dialects import postgresql

    try:
        compiled = col.type.compile(dialect=postgresql.dialect()).upper()
    except Exception:  # pragma: no cover - exotic types fall back to str()
        compiled = str(col.type).upper()
    if "JSONB" in compiled or compiled.startswith("JSON"):
        return "json"
    if "UUID" in compiled:
        return "uuid"
    if "BOOL" in compiled:
        return "bool"
    if "TIMESTAMP" in compiled:
        return "ts"
    if compiled.startswith("DATE"):
        return "date"
    if "INT" in compiled:
        return "int"
    if any(x in compiled for x in ("NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")):
        return "num"
    if "ARRAY" in compiled or "[]" in compiled:
        return "array"
    if any(x in compiled for x in ("CHAR", "TEXT", "VARCHAR", "STRING")):
        return "text"
    return "other"


def _db_type_category(udt: str) -> str:
    udt = udt.lower()
    if udt.startswith("_"):
        return "array"
    return {
        "json": "json", "jsonb": "json", "uuid": "uuid", "bool": "bool",
        "timestamp": "ts", "timestamptz": "ts", "date": "date",
        "int2": "int", "int4": "int", "int8": "int",
        "numeric": "num", "float4": "num", "float8": "num",
        "varchar": "text", "text": "text", "bpchar": "text", "char": "text",
    }.get(udt, "other")


def test_every_orm_table_exists_in_migrated_db(admin_sync_url):
    db = _db_columns(admin_sync_url)
    db_tables = {t for t, _ in db}
    missing = sorted(set(Base.metadata.tables) - db_tables)
    assert not missing, (
        "ORM tables missing from the migrated database — add a migration "
        f"(this is the 039/040 drift class): {missing}"
    )


def test_every_orm_column_exists_in_migrated_db(admin_sync_url):
    db = _db_columns(admin_sync_url)
    db_tables = {t for t, _ in db}
    missing = [
        f"{tname}.{col.name}"
        for tname, tbl in Base.metadata.tables.items()
        if tname in db_tables
        for col in tbl.columns
        if (tname, col.name) not in db
    ]
    assert not missing, (
        "ORM columns missing from the migrated database — every read of these "
        f"500s on real Postgres; add a migration: {sorted(missing)}"
    )


def test_nullability_parity(admin_sync_url):
    db = _db_columns(admin_sync_url)
    risky = []
    for tname, tbl in Base.metadata.tables.items():
        for col in tbl.columns:
            key = (tname, col.name)
            if key not in db or col.primary_key or key in NULLABILITY_ALLOWLIST:
                continue
            meta = db[key]
            # ORM thinks NULL is fine but the DB will reject it and the app
            # 500s at insert time (the assets.workcell_id class).
            if col.nullable and not meta["nullable"] and meta["default"] is None:
                risky.append(f"{tname}.{col.name}")
    assert not risky, (
        "ORM-nullable columns that the migrated DB requires (insert-time 500 "
        f"risk — align the ORM/schema or allowlist with a reason): {sorted(risky)}"
    )


def test_id_column_type_parity(admin_sync_url):
    """uuid-vs-text drift on id columns is the class 032 consolidated away."""
    db = _db_columns(admin_sync_url)
    drift = []
    for tname, tbl in Base.metadata.tables.items():
        for col in tbl.columns:
            key = (tname, col.name)
            if key not in db or key in TYPE_ALLOWLIST:
                continue
            if not (col.name == "id" or col.name.endswith("_id")):
                continue
            orm_cat = _orm_type_category(col)
            db_cat = _db_type_category(db[key]["udt"])
            if {orm_cat, db_cat} == {"uuid", "text"}:
                drift.append(f"{tname}.{col.name}: ORM={orm_cat} DB={db_cat}")
    assert not drift, (
        "uuid-vs-text drift on id columns (binds/joins break on real Postgres "
        f"— the pre-032 class): {sorted(drift)}"
    )
