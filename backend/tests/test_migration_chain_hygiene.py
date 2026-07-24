"""The production migration chain must contain schema, not sample data (FS-203).

Four migrations — 005_populate_test_kanban_data, 006_populate_extended_kanban_data,
008_populate_actionable_registries, 009_dev_floor_sample_data — insert demo rows
(test kanban cards, sample registries, a fake "dev floor" of assets). They sat in
the ordinary chain, so every real deployment silently received fake operational
data alongside its schema.

migrate.py now skips them unless `--with-dev-fixtures` is passed. These tests
keep that true and stop a NEW data-only migration slipping in behind it.

Static, no database needed: this is about what the chain contains.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"

# The four known fixtures. Gated in migrate.py, deliberately not deleted: DBs
# that already ran them have the versions recorded, and removing the files would
# look like history tampering.
KNOWN_FIXTURES = {
    "005_populate_test_kanban_data.sql",
    "006_populate_extended_kanban_data.sql",
    "008_populate_actionable_registries.sql",
    "009_dev_floor_sample_data.sql",
}

# Statements that define or change schema. A migration containing any of these is
# doing structural work, whatever else it also does.
DDL = re.compile(
    r"\b(CREATE|ALTER|DROP)\s+(TABLE|INDEX|VIEW|TYPE|SCHEMA|POLICY|FUNCTION|"
    r"TRIGGER|SEQUENCE|EXTENSION|MATERIALIZED)\b",
    re.I,
)
INSERT = re.compile(r"^\s*INSERT\s+INTO\b", re.I | re.M)


def _sql_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def _is_data_only(path: Path) -> bool:
    """INSERTs rows and performs no schema work at all."""
    text = path.read_text()
    return bool(INSERT.search(text)) and not DDL.search(text)


def test_the_known_fixtures_are_gated_in_migrate():
    """migrate.py must still recognise every known fixture by name."""
    migrate = (Path(__file__).resolve().parents[1] / "scripts" / "migrate.py").read_text()
    assert "DEV_FIXTURE_PREFIXES" in migrate, (
        "migrate.py no longer gates demo fixtures — production runs would insert "
        "fake kanban cards and sample assets again"
    )
    for name in KNOWN_FIXTURES:
        stem = name.rsplit(".", 1)[0]
        assert stem in migrate, (
            f"{name} is a demo-data migration but is not listed in "
            "DEV_FIXTURE_PREFIXES, so it would apply to production"
        )


def test_no_new_data_only_migrations():
    """A new migration that only INSERTs rows belongs in the seeder, not the chain."""
    offenders = sorted(
        p.name for p in _sql_files()
        if p.name not in KNOWN_FIXTURES and _is_data_only(p)
    )
    assert not offenders, (
        "these migrations only INSERT rows and do no schema work — they will run "
        "on every production deployment. Put sample data in "
        "backend/scripts/seed_demo_data.py instead: " + ", ".join(offenders)
    )


def test_known_fixture_list_is_not_stale():
    """If a listed fixture stops being data-only (or vanishes), update the list."""
    present = {p.name for p in _sql_files()}
    missing = sorted(KNOWN_FIXTURES - present)
    assert not missing, (
        f"listed fixtures no longer exist — remove them from KNOWN_FIXTURES: {missing}"
    )
    not_data_only = sorted(
        name for name in KNOWN_FIXTURES if not _is_data_only(MIGRATIONS / name)
    )
    assert not not_data_only, (
        "these are listed as demo-data fixtures but now contain schema work, so "
        f"gating them would skip real DDL: {not_data_only}"
    )


def test_migration_numbering_has_no_unexplained_gap():
    """Document the 019 gap rather than leaving it to be rediscovered.

    A missing number is harmless to the runner (it keys on the full filename),
    but an unexplained gap reads like a lost migration during review. This pins
    the only known gap so a NEW one is noticed.
    """
    prefixes = sorted({int(p.name.split("_", 1)[0]) for p in _sql_files()})
    gaps = [
        n for n in range(prefixes[0], prefixes[-1] + 1) if n not in set(prefixes)
    ]
    assert gaps == [19], (
        "unexpected gap(s) in migration numbering. 019 is a known historical gap "
        f"(never authored); anything else suggests a lost file: {gaps}"
    )
