"""Every migration can be re-run at its own point in the chain (FS-578).

THE RUNNER CANNOT OFFER ATOMICITY, so idempotency is the entire safety net.
`scripts/migrate.py` connects with `autocommit = True` and executes each statement
separately, because TimescaleDB continuous aggregates, `add_retention_policy` and
`CREATE INDEX CONCURRENTLY` all refuse to run inside a transaction block. The consequence is
not written down anywhere: **a migration that fails at statement 7 of 12 has already committed
statements 1 through 6, and its version row is never written.** There is no rollback. The only
recovery an operator has is to run the file again — which works if, and only if, the first six
statements can be executed twice.

`database/migrations/README.md` has said "make statements idempotent" since FS-56. Nothing
enforced it, and the honest reason nothing did is that **the static check over-reports by
five to one.** Postgres gives no `IF NOT EXISTS` for a policy, a trigger or a constraint, so
the repository's idiom is `DROP POLICY IF EXISTS x ON t;` followed by `CREATE POLICY x ON t`,
or an `ADD CONSTRAINT` inside a guarded `DO $$` block. A text sweep sees the bare `CREATE` and
reports a defect. Twenty-two files look wrong that way. **Four actually are** — which this
file establishes by running them against a real database rather than reading them.

WHAT CANNOT BE FIXED, AND WHY IT MATTERS THAT NOBODY TRIES. All four are early migrations that
every existing database has already applied, and `migrate.py` refuses to run against a
database whose recorded checksum no longer matches the file:

    REFUSING to migrate: applied migration(s) were edited after being recorded

So repairing `001_init.sql` in place would not improve anything — it would take every deployed
database out of service until somebody ran `--rebaseline-drifted`. The four are permanent, and
this guard is forward-only: it exists to stop a **new** migration joining them.
"""

from __future__ import annotations

import pathlib
import re
from typing import Dict, List, Tuple

import pytest

pytest.importorskip("psycopg2")
pytest.importorskip("sqlparse")

MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "database" / "migrations"

#: Migrations that fail when re-run, with the statement and why it cannot be repaired.
#: **Named rather than counted** — a count can be satisfied by deleting a migration, which
#: would improve the number and break every database that has not applied it yet.
#:
#: Measured against timescaledb:latest-pg15 on 2026-08-08 by applying the chain from empty and
#: re-running each file immediately after it succeeded.
NOT_RERUNNABLE: Dict[str, str] = {
    "001_init.sql": (
        "`CREATE TABLE organizations` with no IF NOT EXISTS — the first statement of the "
        "first migration. Applied by every database in existence; editing it is checksum "
        "drift and the runner refuses to migrate at all until the operator rebaselines."
    ),
    "002_continuous_aggregates.sql": (
        "`CREATE MATERIALIZED VIEW … WITH (timescaledb.continuous)`, which has no IF NOT "
        "EXISTS form in the TimescaleDB version this migration was written against. "
        "034_historian_retention.sql shows the modern spelling does support it; 002 predates "
        "that and cannot be edited now."
    ),
    "004_query_optimization.sql": (
        "Two bare `CREATE INDEX` statements. The only file of the four whose fix would be a "
        "one-word edit, and the same checksum rule applies."
    ),
    "010_api_keys.sql": (
        "`INSERT INTO permissions … VALUES` with no ON CONFLICT: a re-run raises "
        "duplicate key value violates unique constraint \"permissions_name_key\". This is "
        "the only one of the four that is a DATA statement, and the only one whose partial "
        "re-run would leave a half-populated permission set rather than simply stopping."
    ),
}

#: Statements the harness could not retry, by file. A second file appearing here is a
#: coverage loss, and it should be seen rather than absorbed.
#:
#: This UNDERCOUNTS by construction, which is the honest thing to say about it: the retry
#: stops at the first real failure, so `001_init.sql`'s `add_retention_policy` is never
#: reached — the file is already known-bad at statement one. The number describes what the
#: harness declined to try, not every statement in the tree that would refuse a transaction.
UNCHECKED: Dict[str, int] = {
    "005_data_retention.sql": 2,
}

#: Postgres' own words for "the harness cannot judge this one". `add_retention_policy`,
#: `CREATE INDEX CONCURRENTLY` and a `WITH DATA` continuous aggregate all refuse a transaction
#: block, so the retry cannot be attempted without leaving state behind.
#:
#: Detected from the ERROR rather than from a pattern list. A list of statement shapes is a
#: second place to keep the same fact, and it is wrong in both directions: it missed
#: `CREATE MATERIALIZED VIEW … WITH (timescaledb.continuous)` on the first run, and marking
#: that shape hostile wholesale would have HIDDEN 002, which fails the retry for an unrelated
#: reason — it has no IF NOT EXISTS, so the duplicate check fires before the transaction check.
CANNOT_BE_TRIED = "cannot run inside a transaction block"


def _statements(path: pathlib.Path) -> List[str]:
    """Split a migration the way `migrate.py` does, minus its transaction keywords.

    `BEGIN`/`COMMIT` are dropped because the harness supplies its own transaction; seventeen
    migrations wrap themselves, which makes them atomic on a real run and is a second valid
    answer to the same problem.
    """
    import sqlparse

    out = []
    for chunk in sqlparse.split(path.read_text()):
        text = sqlparse.format(chunk, strip_comments=True).strip()
        if not text:
            continue
        if re.split(r"[\s;]", text.upper(), 1)[0] in ("BEGIN", "COMMIT"):
            continue
        out.append(text)
    return out


def _rerun_report(dsn: str) -> Tuple[Dict[str, Tuple[str, str]], Dict[str, int]]:
    """Apply the chain from empty; after each file, re-run it and record the first failure.

    The re-run happens **immediately after that migration succeeded**, not at the end of the
    chain. Running everything and then re-running each file measures something else entirely:
    `010_api_keys.sql` would fail with `relation "permissions" does not exist` because
    `037_remove_unused_permission_rbac.sql` legitimately dropped that table twenty-seven
    migrations later, and `009_dev_floor_sample_data.sql` would fail on a column
    `040_metadata_column_rename.sql` renamed. Neither is an idempotency defect, and a guard
    that reported them would be teaching people to ignore it.
    """
    import psycopg2

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    failures: Dict[str, Tuple[str, str]] = {}
    unchecked: Dict[str, int] = {}
    try:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            statements = _statements(path)

            with conn.cursor() as cur:  # advance the chain for real
                for statement in statements:
                    cur.execute(statement)

            # Re-run inside a transaction that is always discarded, so the database is left
            # exactly as the apply above left it. A statement Postgres refuses to run in a
            # transaction is recorded as unchecked and the retry resumes after it, in a fresh
            # transaction — the earlier statements' effects are gone, but they were rolled
            # back either way, and on a real retry an idempotent statement is a no-op.
            index = 0
            conn.autocommit = False
            while index < len(statements):
                try:
                    with conn.cursor() as cur:
                        while index < len(statements):
                            cur.execute(statements[index])
                            index += 1
                except Exception as error:  # noqa: BLE001 — the failure IS the measurement
                    message = str(error).strip().splitlines()[0]
                    conn.rollback()
                    if CANNOT_BE_TRIED in message:
                        unchecked[path.name] = unchecked.get(path.name, 0) + 1
                        index += 1
                        continue
                    failures[path.name] = (
                        " ".join(statements[index].split())[:90],
                        message[:110],
                    )
                    break
            conn.rollback()
            conn.autocommit = True
    finally:
        conn.close()
    return failures, unchecked


@pytest.fixture(scope="module")
def rerun_report(admin_sync_url: str):
    """Build a scratch database on the session container and measure the chain in it.

    A scratch database rather than the suite's own: this applies all 65 migrations and then
    re-runs every one of them, which takes DDL locks on every table in the schema. Doing that
    to the database the rest of the suite is using would be a needless way to make an
    unrelated test flake.
    """
    import psycopg2

    scratch = "migration_rerun_check"
    admin = psycopg2.connect(admin_sync_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS {scratch}')
            cur.execute(f'CREATE DATABASE {scratch}')
        scratch_dsn = re.sub(r"/[^/?]+$", f"/{scratch}", admin_sync_url)
        try:
            yield _rerun_report(scratch_dsn)
        finally:
            with admin.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS {scratch} WITH (FORCE)')
    finally:
        admin.close()


class TestTheHarnessIsMeasuringSomething:
    def test_it_reads_the_chain(self):
        """Vacuity. A glob that matched nothing would pass every assertion below over an
        empty set, which is the shape three guards in this suite have already had."""
        files = sorted(MIGRATIONS.glob("*.sql"))
        assert len(files) > 60, f"only {len(files)} migrations found; the path is wrong"

    def test_the_chain_applies_from_empty(self, rerun_report):
        """The strongest thing this file asserts, and it is a side effect of the fixture: a
        fresh database can be built from the migrations alone. If any statement had failed,
        the fixture would have raised before a single test ran."""
        assert rerun_report is not None

    def test_the_known_failures_are_still_failures(self, rerun_report):
        """A stale entry excuses a migration that is now fine and hides the next one. This
        also proves the harness can still detect the defect — without it, a harness that
        silently stopped executing would report a clean chain."""
        failures, _ = rerun_report
        fixed = sorted(set(NOT_RERUNNABLE) - set(failures))
        assert not fixed, (
            f"{fixed} are recorded as not re-runnable and now re-run cleanly. If they were "
            f"edited, every database that already applied them is now refusing to migrate on "
            f"checksum drift — check that before deleting the entries."
        )


class TestNoNewMigrationBreaksRecovery:
    def test_every_migration_can_be_run_twice(self, rerun_report):
        failures, _ = rerun_report
        new = {name: detail for name, detail in failures.items() if name not in NOT_RERUNNABLE}
        assert not new, (
            "these migrations cannot be re-run, and re-running is the ONLY recovery the "
            "runner offers. `migrate.py` executes statements one at a time in autocommit "
            "because continuous aggregates and retention policies refuse a transaction "
            "block, so a failure halfway through leaves the earlier statements committed and "
            "no version recorded:\n\n  "
            + "\n  ".join(f"{n}\n      {s}\n      -> {m}" for n, (s, m) in sorted(new.items()))
            + "\n\nUse IF NOT EXISTS where Postgres offers it. Where it does not — policies, "
            "triggers, constraints — the idiom in this tree is `DROP … IF EXISTS` before the "
            "CREATE, or a guarded `DO $$ … IF NOT EXISTS … $$` block. Wrapping the file in "
            "BEGIN/COMMIT is the other valid answer, and seventeen migrations take it."
        )

    def test_the_unchecked_statements_are_named(self, rerun_report):
        """A statement the harness skipped is not a statement that passed. Postgres refuses
        to roll back `add_retention_policy`, so the harness cannot try it twice — and a guard
        that reported those files as verified would be overstating what it knows."""
        _, unchecked = rerun_report
        assert unchecked == UNCHECKED, (
            f"the set of statements the harness cannot retry changed.\n  measured: "
            f"{dict(sorted(unchecked.items()))}\n  recorded: {dict(sorted(UNCHECKED.items()))}\n"
            f"A new one means a migration added a statement that refuses a transaction block "
            f"— legitimate, but it is now UNVERIFIED and needs recording here rather than "
            f"passing quietly."
        )


class TestTheConventionIsWrittenDown:
    """The rule existed and was unenforced for 62 migrations. Enforcement without the
    explanation is how somebody 'fixes' 001_init.sql and takes production offline."""

    def test_the_readme_says_a_migration_must_be_rerunnable(self):
        readme = (MIGRATIONS / "README.md").read_text()
        assert "idempotent" in readme.lower()

    def test_the_readme_names_the_four_that_are_not(self):
        readme = (MIGRATIONS / "README.md").read_text()
        missing = [name for name in NOT_RERUNNABLE if name not in readme]
        assert not missing, (
            f"{missing} fail on re-run and the README does not say so. An operator "
            f"recovering a half-applied migration at 3am needs to know which files will not "
            f"survive the retry BEFORE they run it."
        )


def test_the_runner_still_uses_autocommit():
    """The premise. Everything above matters because there is no transaction to roll back;
    if the runner ever gains one, this file's reasoning needs rewriting rather than deleting.
    """
    runner = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrate.py").read_text()
    assert "conn.autocommit = True" in runner, (
        "migrate.py no longer runs in autocommit. If it now wraps each migration in a "
        "transaction, a partial application is impossible and idempotency stops being the "
        "recovery path — re-read this file's docstring before changing the allowlist."
    )
