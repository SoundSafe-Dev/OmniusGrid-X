"""Every id-shaped field on a request schema is a tenant reference or says why not (FS-737).

THE PART OF THE FIX THAT OUTLIVES THE FIX. Six instances of one class were closed one at a
time — operations, four shop-floor writes, two notification subscriptions, insight
activation, six kanban task links — and the seventh started from zero exactly like the
first, because a handler-by-handler fix leaves nothing behind that a NEW field has to pass.

So this file asserts the accounting, not the behaviour: every field on a request model in
`app/models/schemas.py` whose name ends `_id` (plus `assigned_to`, which is a user id
wearing a different name) appears either in `TENANT_REFS`, where it is verified, or in
`NOT_TENANT_SCOPED` with a reason. A field added next year fails the build.

WHAT THIS FILE CANNOT DO. It proves the registry is complete over the schemas; it does not
prove any route CALLS `verify_refs`. That is `test_a_tenant_reference_is_refused_realdb.py`,
which drives the routes over HTTP against a real database. Both are needed and neither
substitutes for the other — the accounting can be perfect while a handler ignores it.

WHY KEYED BY FIELD NAME. One entry covers every route that accepts `carrier_id`, including
routes not written yet, which is the whole point. The risk it accepts is a name reused for
a different table, so `test_no_field_name_means_two_tables` checks that the id columns
sharing a name really do point at one table.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from app.core.tenant_refs import NOT_TENANT_SCOPED, TENANT_REFS

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SCHEMAS = BACKEND / "app" / "models" / "schemas.py"
MODELS = BACKEND / "app" / "db" / "models.py"

#: A request model is one a route can bind to a body. The suffixes are the codebase's own
#: naming, and `BODY_PARAM` in `test_declared_body_fields_reach_the_service.py` uses the
#: identical set — if one drifts, the two sweeps stop describing the same population.
REQUEST_MODEL = re.compile(r"(Create|Update|Request|Input|In)$")

#: `assigned_to` is a `users.id` that does not end in `_id`. Any other such name has to be
#: added here by hand, which is a cost worth paying: the alternative is matching on type,
#: and every one of these is a bare `str` or `UUID`.
EXTRA_ID_FIELDS = {"assigned_to"}


def _id_fields() -> dict[str, set[str]]:
    """field name -> the request models that declare it."""
    tree = ast.parse(SCHEMAS.read_text())
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not REQUEST_MODEL.search(node.name):
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            name = stmt.target.id
            if name.endswith("_id") or name in EXTRA_ID_FIELDS:
                out.setdefault(name, set()).add(node.name)
    return out


def _column_targets() -> dict[str, set[str]]:
    """column name -> the tables its ForeignKey points at, across `db/models.py`."""
    source = MODELS.read_text()
    out: dict[str, set[str]] = {}
    for match in re.finditer(
        r"^\s{4}(\w+) = UUIDForeignKey\(\s*[\"'](\w+)\.", source, re.M
    ):
        out.setdefault(match.group(1), set()).add(match.group(2))
    return out


class TestTheMeasurementIsReal:
    def test_the_schemas_parse_to_something(self):
        """Vacuity. If the AST walk or the suffix regex breaks, every assertion below
        passes over an empty dict — the way a register rots unnoticed."""
        fields = _id_fields()
        assert len(fields) > 30, (
            f"only {len(fields)} id-shaped request fields found in {SCHEMAS.name}; the "
            f"population measured when this was written was 89 fields across 35 models"
        )
        assert "carrier_id" in fields, "a known reference was not found at all"

    def test_the_registry_is_not_empty(self):
        assert len(TENANT_REFS) > 15, f"only {len(TENANT_REFS)} references registered"

    def test_every_registered_field_builds_a_query(self):
        """Each entry is a callable; one that raises would fail at request time on a route
        nobody exercises, which is exactly when it must not."""
        for field, build in TENANT_REFS.items():
            query = build("00000000-0000-0000-0000-000000000000",
                          "00000000-0000-0000-0000-000000000001")
            compiled = str(query)
            assert "WHERE" in compiled, f"{field} builds a query with no predicate"
            assert "organization_id" in compiled, (
                f"{field} builds a query that never mentions organization_id — it would "
                f"return a row for any tenant and the check would pass on every id"
            )


class TestEveryFieldIsAccountedFor:
    def test_no_id_field_is_unaccounted(self):
        unaccounted = sorted(
            f"{field} (on {', '.join(sorted(models))})"
            for field, models in _id_fields().items()
            if field not in TENANT_REFS and field not in NOT_TENANT_SCOPED
        )
        assert not unaccounted, (
            f"{unaccounted} are id-shaped request fields that are neither verified nor "
            f"explained. A foreign key is checked BELOW row-level security, so a body "
            f"naming another tenant's row is accepted by the database and only the handler "
            f"can refuse it. Add the field to TENANT_REFS with the query that proves "
            f"ownership, or to NOT_TENANT_SCOPED with the reason it is not a reference."
        )

    def test_no_field_is_both_registered_and_exempt(self):
        both = sorted(set(TENANT_REFS) & set(NOT_TENANT_SCOPED))
        assert not both, f"{both} are both verified and declared not to be references"

    @pytest.mark.parametrize("field", sorted(NOT_TENANT_SCOPED))
    def test_every_exemption_states_a_reason(self, field: str):
        reason = NOT_TENANT_SCOPED[field].strip()
        assert len(reason) > 60, (
            f"{field} is exempt with a {len(reason)}-character reason. An exemption whose "
            f"argument is not written down is re-litigated by every reader, and eventually "
            f"granted to a field that did not deserve it."
        )

    def test_no_exemption_is_stale(self):
        """An entry for a field no schema declares any more overstates what was reviewed."""
        declared = set(_id_fields())
        stale = sorted(f for f in NOT_TENANT_SCOPED if f not in declared)
        assert not stale, (
            f"{stale} are exempt and no request schema declares them. Remove them; the "
            f"register should describe the code as it is."
        )

    def test_no_registration_is_stale(self):
        """The registry may cover a field ahead of its first schema — but not many, or it
        stops describing anything. Listed explicitly so the exception is visible."""
        declared = set(_id_fields())
        unused = sorted(f for f in TENANT_REFS if f not in declared)
        assert len(unused) <= 2, (
            f"{unused} are registered and declared by no request schema. Registering a "
            f"field before its schema exists is fine once; a list of them means the "
            f"registry has drifted from the models."
        )


class TestTheKeyIsSafeToUse:
    def test_no_field_name_means_two_tables(self):
        """The registry is keyed by FIELD NAME, so one entry covers every route that
        accepts it — including routes not written yet, which is the point. The risk is a
        name reused for a different table: `carrier_id` verified against `carriers` would
        be wrong if some other model used the same name for something else. Checked
        against the real foreign keys rather than assumed."""
        collisions = {
            column: sorted(tables)
            for column, tables in _column_targets().items()
            if len(tables) > 1 and (column in TENANT_REFS or column in NOT_TENANT_SCOPED)
        }
        assert not collisions, (
            f"{collisions} — a registered field name points at more than one table, so a "
            f"single registry entry cannot be right for both. Verify per route instead, "
            f"and record why here."
        )
