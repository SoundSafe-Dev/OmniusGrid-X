"""Every Postgres extension the schema needs must be created by a MIGRATION.

`tests/conftest.py` runs `CREATE EXTENSION IF NOT EXISTS pgcrypto;` when it builds a
test container. No migration did. So the real-DB suite had a working audit trail while
a real deployment did not:

    009_audit_logs.sql triggers on every INSERT into audit_logs and calls
    calculate_audit_hash(), whose body is encode(digest(...), 'hex') — digest() is
    pgcrypto. Without the extension the trigger raises UndefinedFunctionError, and
    app/services/audit.py catches it deliberately ("never fail the audited
    operation"), logs audit_log_write_failed, and lets the request through.

Every audited action succeeded and every audit row was rejected. Verified on a freshly
migrated database before 059 landed: a manual INSERT failed and `SELECT count(*)`
returned 0. The tests were not wrong about the code — they were wrong about the
database, because the harness had quietly supplied what production would not.

**That is the general failure this guard exists for.** A test fixture that provisions
something the migrations do not makes the suite an unreliable witness for exactly the
environments nobody can inspect by hand. The extension is the instance; the divergence
is the class.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "database" / "migrations"
CONFTEST = Path(__file__).resolve().parent / "conftest.py"

#: Extensions that exist without being created, so a migration need not.
BUILT_IN = {"plpgsql"}


def _extensions_created_in(paths) -> set[str]:
    found = set()
    pattern = re.compile(r"CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"']?(\w+)", re.I)
    for p in paths:
        for m in pattern.finditer(p.read_text(errors="ignore")):
            found.add(m.group(1).lower())
    return found


def test_the_sweep_can_see_both_sides():
    """A guard that reads nothing passes for the wrong reason."""
    assert MIGRATIONS.is_dir(), f"{MIGRATIONS} is gone; this guard checks nothing"
    assert CONFTEST.exists(), f"{CONFTEST} is gone; this guard checks nothing"
    assert len(list(MIGRATIONS.glob("*.sql"))) > 40, "migration directory looks wrong"


def test_no_extension_is_created_only_by_the_test_harness():
    in_conftest = _extensions_created_in([CONFTEST]) - BUILT_IN
    in_migrations = _extensions_created_in(sorted(MIGRATIONS.glob("*.sql"))) - BUILT_IN

    harness_only = sorted(in_conftest - in_migrations)
    assert not harness_only, (
        "these extensions are created by the test harness but by no migration, so the "
        f"suite tests a database that deployments will not have: {harness_only}\n\n"
        "Add a migration that creates it. A fixture standing in for a migration makes "
        "the tests pass and the deployment fail — which is how the audit trail came to "
        "discard every row while its tests were green."
    )


def test_pgcrypto_specifically_is_migrated():
    """The instance that motivated this guard, pinned by name.

    Kept separate from the sweep above so the failure message names the consequence
    rather than a set difference: without pgcrypto the audit hash-chain trigger raises
    and app/services/audit.py swallows it, leaving no audit trail at all.
    """
    in_migrations = _extensions_created_in(sorted(MIGRATIONS.glob("*.sql")))
    assert "pgcrypto" in in_migrations, (
        "no migration creates pgcrypto. 009_audit_logs.sql's hash-chain trigger calls "
        "digest(), so every INSERT into audit_logs will raise UndefinedFunctionError — "
        "and audit.py catches it, so the only symptom is an empty audit trail."
    )
