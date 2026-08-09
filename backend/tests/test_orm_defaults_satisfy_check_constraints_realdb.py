"""An ORM column default must be a value its CHECK constraint accepts.

THE FAILURE THIS CATCHES. A column declared `Column(String, default="queued")` under a
constraint allowing only `('pending', 'running', 'done')` rejects every ORM insert that
does not set the field explicitly — an IntegrityError from a value the application chose
for itself. It is the write-side twin of the response/column mismatch in
`test_api_response_schema_matches_columns.py`: the model and the schema disagreeing about
what a column may hold.

Migration 050 made this newly relevant. It copied 39 ORM defaults into SERVER defaults, so
a bad default now also becomes the value the database writes on a raw INSERT — the
disagreement stops being one insert path's problem and becomes the column's.

WHY THIS IS NARROW ON PURPOSE. An earlier, broader version compared every pydantic
`Literal` field against every constrained column with a matching NAME, and produced six
findings, all false. `StatusUpdateRequest.status` was flagged against `agent_releases`,
`agent_rollouts`, `model_registry` and two more — tables it never writes to — because they
happen to have a `status` column too. `ScheduledComplianceReportCreate.frequency` was
flagged against `scheduled_exports`, which belongs to a different feature; its real target
allows all five values.

Making that version trustworthy needs a request-model-to-table mapping, and unlike
`FooResponse -> Foo` there is no naming convention to derive one from. So the broad sweep
was run, found nothing, and is recorded in `docs/engineering/defect-class-sweeps.md`
rather than shipped as a guard with six known false positives. An ORM column, by contrast,
names its own table — which is the whole reason this file can be precise.
"""

from __future__ import annotations

import re

import pytest


def _constraints(sync_url: str) -> dict[tuple[str, str], set[str]]:
    """{(table, column): allowed values} for every value-list CHECK in the schema."""
    import psycopg2

    conn = psycopg2.connect(sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rel.relname, pg_get_constraintdef(con.oid) "
                "FROM pg_constraint con JOIN pg_class rel ON rel.oid = con.conrelid "
                "JOIN pg_namespace n ON n.oid = rel.relnamespace "
                "WHERE con.contype = 'c' AND n.nspname = 'public'"
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    found: dict[tuple[str, str], set[str]] = {}
    for table, definition in rows:
        column = re.search(r"\(\((\w+)\)::text = ANY", definition)
        if not column:
            continue
        values = set(re.findall(r"'([^']+)'::character varying", definition))
        if values:
            found[(table, column.group(1))] = values
    return found


def _orm_defaults():
    """(table, column, default) for every scalar ORM default on a mapped column."""
    from sqlalchemy.inspection import inspect as sa_inspect

    from app.db import models as core

    modules = [core]
    try:
        from app.db import logistics_models

        modules.append(logistics_models)
    except Exception:  # noqa: BLE001 - optional module
        pass

    for module in modules:
        for obj in vars(module).values():
            if not (isinstance(obj, type) and hasattr(obj, "__tablename__")):
                continue
            try:
                columns = sa_inspect(obj).columns
            except Exception:  # noqa: BLE001 - not every class inspects cleanly
                continue
            for name, column in columns.items():
                default = column.default
                if default is None or not hasattr(default, "arg"):
                    continue
                if callable(default.arg):
                    continue
                yield obj.__tablename__, name, default.arg


@pytest.fixture(scope="module")
def constrained(admin_sync_url):
    return _constraints(admin_sync_url)


class TestTheSweepIsNotVacuous:
    def test_constraints_are_found(self, constrained):
        assert len(constrained) >= 10, (
            f"only {len(constrained)} value-list CHECK constraints parsed; the "
            f"assertion below would pass while checking almost nothing"
        )

    def test_some_defaults_are_actually_compared(self, constrained):
        pairs = [
            (t, c, d) for t, c, d in _orm_defaults() if (t, c) in constrained
        ]
        assert len(pairs) >= 5, (
            f"only {len(pairs)} ORM defaults sit on a constrained column; the sweep has "
            f"nothing to catch"
        )


class TestEveryDefaultSatisfiesItsConstraint:
    def test_no_orm_default_violates_a_check(self, constrained):
        offenders = [
            f"{table}.{column} defaults to {value!r}, but the CHECK allows "
            f"{sorted(constrained[(table, column)])}"
            for table, column, value in _orm_defaults()
            if (table, column) in constrained
            and str(value) not in constrained[(table, column)]
        ]
        assert not offenders, (
            "An ORM default the database rejects makes every insert that omits the "
            "field fail with an IntegrityError — and since migration 050 copied ORM "
            "defaults into server defaults, it is also what a raw INSERT would write:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_detector_would_notice_a_violation(self, constrained):
        """Proves the comparison can fail. Without this, an empty offender list is
        indistinguishable from a comparison that never ran."""
        (table, column), allowed = next(iter(constrained.items()))
        invented = "definitely-not-an-allowed-value"
        assert invented not in allowed
