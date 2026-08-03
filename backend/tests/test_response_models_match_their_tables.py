"""Every field a response model declares must come from somewhere.

FastAPI drops whatever `response_model` does not name, and this session lost two features to
exactly that: `AssetResponse` never declared `maintenance_mode`, so a column, a write endpoint
and an engine that honoured it added up to a feature no client could see; and `DockDoorResponse`
would have swallowed the trailer plate the handler had just resolved.

The reverse direction is this file. A response model that declares a field **nothing produces**
is the same defect facing outward: the schema promises a value, pydantic supplies its default,
and the client renders it. `DockDoor` declared five such fields — `supportedEquipment` (the
column is `equipment_capabilities`, a JSON object, not a list), `hasLoadingEquipment`,
`maxWeightCapacity`, `currentAppointmentId`, and `estimatedReleaseAt`, which rendered
"Release: HH:MM" for a prediction nothing computes.

WHY THIS IS STRONGER THAN THE WIRE-VOCABULARY SWEEP NEXT DOOR. That sweep asks whether a name
exists anywhere in the backend, so it credits a field whose name happens to be a column on
some other table — rule 34, and it is what hid four of DockDoor's five. This asks a narrower
question with a definite answer: **is this field a column of THIS entity's table, an alias of
one, or an explicitly-listed value the handler resolves?** No vocabulary, no heuristics, and
the pairing is by name (`DockDoorResponse` ↔ `DockDoor`).

WHAT IT FOUND: nothing new. Both current exceptions are legitimate and listed below. That is
worth recording — "proven clean" and "never checked" look identical afterwards, and only one
of them justifies not looking again.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

import app.models.schemas as schemas
from app.db import logistics_models, models

#: Fields a response model may declare that are NOT columns of its table, with the reason.
#: Each is a promise that something else fills the value — and a promise this file cannot
#: verify, so the list stays short and every entry says who fills it.
RESOLVED_ELSEWHERE: dict[str, str] = {
    "DockDoorResponse.trailer_license_plate": (
        "denormalised by get_dock_doors from yard_trailers via current_trailer_id, in one "
        "batched query. Pinned by test_yard_trailer_plate_is_resolved.py."
    ),
    "TaskColumnResponse.task_count": (
        "computed by the kanban board handler with a batched GROUP BY (kanban.py), not "
        "stored. Nothing renders it today, but it is resolved rather than defaulted."
    ),
}


def _tables() -> dict[str, set[str]]:
    """{model class name -> its column names}, across both model modules."""
    found: dict[str, set[str]] = {}
    for module in (models, logistics_models):
        for name in dir(module):
            obj = getattr(module, name)
            table = getattr(obj, "__table__", None)
            if table is not None:
                found[name] = {c.name for c in table.columns}
    return found


def _response_models() -> dict[str, type[BaseModel]]:
    found = {}
    for name in dir(schemas):
        obj = getattr(schemas, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel) and name.endswith("Response"):
            found[name] = obj
    return found


def _unsourced(model: type[BaseModel], columns: set[str]) -> list[str]:
    """Fields whose name — or any validation alias — is not a column.

    The alias check is what keeps `metadata` off this list: the column is `meta_data` and the
    schema exposes it as `metadata` through `AliasChoices`. Fourteen models use that pattern,
    and without crediting aliases this guard would report every one of them and be ignored.
    """
    unsourced = []
    for field_name, field in model.model_fields.items():
        names = {field_name}
        alias = getattr(field, "validation_alias", None)
        if alias is not None:
            choices = getattr(alias, "choices", None) or [alias]
            names |= {c for c in choices if isinstance(c, str)}
        if not (names & columns):
            unsourced.append(field_name)
    return sorted(unsourced)


PAIRED = [
    (name, model, _tables()[name[: -len("Response")]])
    for name, model in _response_models().items()
    if name[: -len("Response")] in _tables()
]


class TestTheSweepIsNotVacuous:
    def test_it_pairs_models_with_tables(self):
        # If the naming convention changes, every assertion below passes while checking
        # nothing. 20+ is well under the current count and well over zero.
        assert len(PAIRED) > 20, f"only {len(PAIRED)} response models paired with a table"

    def test_it_reads_real_columns(self):
        tables = _tables()
        assert "id" in tables["DockDoor"]
        assert "current_trailer_id" in tables["DockDoor"]

    def test_an_invented_field_would_be_reported(self):
        """The positive control, on a throwaway model. Without it a clean result says nothing
        about the sweep — method rule 26, learned the hard way in this repository."""

        class FakeResponse(BaseModel):
            id: str
            totallyInventedField: str = ""

        assert _unsourced(FakeResponse, {"id"}) == ["totallyInventedField"]

    def test_an_aliased_field_is_not_reported(self):
        """`metadata` is exposed from the `meta_data` column via AliasChoices on fourteen
        models. Without crediting aliases this guard reports all fourteen and gets ignored."""
        # Only the COLUMN name is offered, deliberately: the field is `metadata` and if the
        # alias were not credited it would be reported. (An earlier version of this line read
        # `{"meta_data", "id"} | {"metadata"} - {"metadata"}`, which evaluates correctly by
        # accident of precedence and tells the reader nothing.)
        model = getattr(schemas, "ShipmentResponse")
        assert "metadata" not in _unsourced(model, {"meta_data", "id"})


class TestEveryDeclaredFieldHasASource:
    @pytest.mark.parametrize("name,model,columns", PAIRED, ids=[p[0] for p in PAIRED])
    def test_no_field_is_declared_without_one(self, name, model, columns):
        """A field with no column and no resolver is a value pydantic will default and the
        client will render — `estimatedReleaseAt` printed "Release: HH:MM" for a prediction
        nothing computes, and four of its neighbours were never reported by the global sweep
        at all because their names are columns on other tables."""
        unsourced = [
            field for field in _unsourced(model, columns)
            if f"{name}.{field}" not in RESOLVED_ELSEWHERE
        ]
        assert not unsourced, (
            f"{name} declares fields that are not columns of its table and are not listed as "
            f"resolved elsewhere: {unsourced}.\n"
            "Either it is a column under a different name (add the alias), something fills "
            "it (add it to RESOLVED_ELSEWHERE with who), or it does not exist (delete it)."
        )


class TestTheExceptionsStayHonest:
    def test_every_exception_is_still_needed(self):
        """An entry for a field that IS a column now is dead weight, and a list nobody prunes
        is a list nobody reads."""
        stale = []
        for entry in RESOLVED_ELSEWHERE:
            model_name, field = entry.rsplit(".", 1)
            model = _response_models().get(model_name)
            columns = _tables().get(model_name[: -len("Response")])
            if model is None or columns is None:
                stale.append(f"{entry} (model or table is gone)")
            elif field not in _unsourced(model, columns):
                stale.append(f"{entry} (now sourced; remove the exception)")
        assert not stale, stale

    def test_every_exception_names_who_fills_it(self):
        for entry, reason in RESOLVED_ELSEWHERE.items():
            assert len(reason) > 40, f"{entry}'s reason is too thin to verify"


# ---------------------------------------------------------------------------------------
# The same pairing, asked about TYPES rather than names (FS-303).
#
# A field can be a real column and still be declared as something the column cannot hold.
# The failure is loud and late: FastAPI validates the RESPONSE, so the handler runs, the
# query succeeds, and the request dies with a 500 on the way out.
#
# It has happened twice, both found by walking a real stack rather than by a test:
#
#   `/nlp/sessions/{id}/data`   `DataSourceResponse.source_id` is declared UUID and the
#                               rows carry 'yard'
#   `/kanban/rules/premade`     the premade template ids are 'template-001'
#
# Neither is reachable from here — `DataSource` and the premade templates have no paired
# table — so this does NOT claim to cover them; they are registered in
# `tests/_lane_failures.py` with owners and expiries. What it covers is the 122 UUID-typed
# fields that ARE paired, where the same mistake would be silent until a row broke it.
#
# THE CONVENTION IS THE WHOLE CHECK. This codebase stores UUIDs as `String(36)` for
# Postgres compatibility (the README's FAQ says so), so "UUID over VARCHAR" is normal and
# tells you nothing — the first version of this probe reported three false positives on
# exactly that basis. What is NOT normal is a UUID declared over a free-form string:
# `GeoTabDiagnostic.vehicle_id` is a `String(100)` holding 'TRK-114', and a response model
# declaring that as a UUID would 500 on every row.
# ---------------------------------------------------------------------------------------

import typing
import uuid as _uuid

import sqlalchemy as _sa

#: The width this codebase uses for a stringified UUID.
_UUID_STRING_LENGTH = 36


def _column_types() -> dict[str, dict[str, object]]:
    found: dict[str, dict[str, object]] = {}
    for module in (models, logistics_models):
        for name in dir(module):
            table = getattr(getattr(module, name), "__table__", None)
            if table is not None:
                found[name] = {c.name: c.type for c in table.columns}
    return found


def _declared(annotation) -> list:
    args = typing.get_args(annotation)
    return [a for a in (args or [annotation]) if a is not type(None)]


def _uuid_fields_over_free_form_strings() -> list[str]:
    types = _column_types()
    offenders = []
    for name, model in _response_models().items():
        columns = types.get(name[: -len("Response")])
        if not columns:
            continue
        for field_name, field in model.model_fields.items():
            column = columns.get(field_name)
            if column is None or _uuid.UUID not in _declared(field.annotation):
                continue
            if isinstance(column, _sa.String) and getattr(column, "length", None) != _UUID_STRING_LENGTH:
                offenders.append(
                    f"{name}.{field_name}: declared UUID over {column} — the column is not "
                    "the 36-char UUID convention, so it may hold anything"
                )
    return offenders


class TestADeclaredTypeCanHoldWhatTheColumnStores:
    def test_the_pairing_reaches_uuid_fields_at_all(self):
        """Vacuity guard. A version of this that paired nothing would pass in silence, and
        the count is the evidence that it is looking at the real surface."""
        types = _column_types()
        seen = 0
        for name, model in _response_models().items():
            columns = types.get(name[: -len("Response")])
            if not columns:
                continue
            seen += sum(
                1 for f, field in model.model_fields.items()
                if f in columns and _uuid.UUID in _declared(field.annotation)
            )
        assert seen >= 80, (
            f"only {seen} paired UUID fields found; the pairing or the annotation "
            "unwrapping has drifted and this check is examining almost nothing"
        )

    def test_no_uuid_field_sits_over_a_free_form_string(self):
        offenders = _uuid_fields_over_free_form_strings()
        assert not offenders, (
            "these response models declare a UUID over a column that need not hold one. "
            "FastAPI validates the RESPONSE, so the handler runs, the query succeeds, and "
            "the request dies with a 500 on the way out — for whichever row happens to "
            "carry a non-UUID value:\n  " + "\n  ".join(offenders)
        )

    def test_the_convention_is_not_flagged(self):
        """The control that stops this becoming noise. 122 UUID fields sit over VARCHAR(36)
        and every one is correct; a check that reported them would be abandoned in a day,
        and the first version of this probe did exactly that."""
        types = _column_types()
        conventional = 0
        for name, model in _response_models().items():
            columns = types.get(name[: -len("Response")])
            if not columns:
                continue
            for field_name, field in model.model_fields.items():
                column = columns.get(field_name)
                if column is None or _uuid.UUID not in _declared(field.annotation):
                    continue
                if getattr(column, "length", None) == _UUID_STRING_LENGTH:
                    conventional += 1
        assert conventional >= 80, (
            f"only {conventional} UUID-over-VARCHAR(36) pairs seen; if the storage "
            "convention changed, the free-form test above is now measuring the wrong thing"
        )
