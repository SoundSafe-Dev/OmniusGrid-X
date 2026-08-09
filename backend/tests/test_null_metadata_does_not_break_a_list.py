"""A NULL `meta_data` column 500'd the whole list endpoint, on twelve schemas.

`metadata: Dict[str, Any] = Field(default_factory=dict)` REJECTS `None`. The factory fires only
when the key is ABSENT — and `model_validate(orm_row)` does not omit the key, it supplies the
attribute's value. For any row not written through the ORM that value is `None`, because
seventeen of the twenty-one `meta_data` columns in the migrations are declared with no DEFAULT.

So the failure is not hypothetical and not per-row: a data import, a partner integration or a
plain `INSERT` produces one NULL, and the LIST endpoint 500s for that tenant. The page, not the
row — `YardTrailerResponse.model_validate` raises inside the loop and the request never returns.

FOUND BY ACCIDENT, which is the part worth recording. A real-DB test for an unrelated fix
(`driverPhone`) seeded its trailers with raw SQL, as every real-DB test in this suite does, and
seven of its eight assertions failed on a validation error that had nothing to do with what was
being tested. Three schemas had already been changed to `Optional[...] = None` one table at a
time — `test_yard_trailer_plate_is_resolved.py` found it on appointments — and the other twelve
were left, because nothing had asked the question across the file.

WHY COERCION RATHER THAN `Optional`. `Optional[...] = None` changes the wire contract: clients
that received `{}` start receiving `null`. NULL metadata and empty metadata mean the same thing
— a row with no extra attributes — so coercing to `{}` keeps the contract and is honest. That is
NOT true of most absent values in this codebase, and is why this one gets a coercion while a
missing cost, a missing estimate and a missing fleet size all stay `None`.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, get_args

import pytest
from pydantic import BeforeValidator, Field, TypeAdapter, ValidationError

from app.models import schemas


def _schemas_with_metadata() -> list[type]:
    found = []
    for _, obj in vars(schemas).items():
        if not (inspect.isclass(obj) and issubclass(obj, schemas.BaseModel)):
            continue
        if "metadata" in getattr(obj, "model_fields", {}):
            found.append(obj)
    return found


def _tolerates_null(model: type) -> bool:
    """Does this schema's `metadata` field accept the NULL its column can hold?

    Two acceptable shapes, and the check is structural rather than a full
    `model_validate`: building a valid instance of each schema means satisfying every OTHER
    required field, which makes the test about those fields instead — the first version of
    this file failed on `status` and `seal_status` and said nothing about metadata at all.

      * `Optional[...]`, which three schemas already used;
      * the `JsonMetadata` coercion, which normalises None to `{}` and keeps the `{}` the
        wire has always carried.
    """
    field = model.model_fields["metadata"]
    if type(None) in get_args(field.annotation):
        return True
    return any(isinstance(m, BeforeValidator) for m in field.metadata)


class TestTheSweepIsNotVacuous:
    def test_it_finds_the_schemas(self):
        """If the scan stops matching, the assertion below passes over an empty set."""
        found = _schemas_with_metadata()
        assert len(found) > 10, f"only {len(found)} schemas declare a metadata field: {found}"

    def test_the_check_can_say_no(self):
        """The positive control. `_tolerates_null` returning True for everything is what a
        broken structural check looks like, and it is indistinguishable from a fixed codebase
        — so it is run against a schema deliberately declared the old way."""

        class _Unfixed(schemas.BaseModel):
            metadata: Dict[str, Any] = Field(default_factory=dict)

        assert not _tolerates_null(_Unfixed), (
            "the check accepts the exact declaration that caused the outage, so its verdict on "
            "the real schemas means nothing"
        )


class TestEverySchemaToleratesTheNullItsColumnHolds:
    def test_no_schema_rejects_a_null_metadata(self):
        """THE ASSERTION THIS FILE EXISTS FOR, across every schema that has the field rather
        than the one that happened to be found."""
        offenders = [m.__name__ for m in _schemas_with_metadata() if not _tolerates_null(m)]
        assert not offenders, (
            f"these schemas reject a NULL metadata column: {offenders}.\n"
            "A raw INSERT produces one — seventeen of the twenty-one meta_data columns have no "
            "DDL default — and `model_validate` then raises inside the list loop, so the whole "
            "PAGE 500s for that tenant, not the one row. Use `JsonMetadata`."
        )


class TestTheCoercionNormalisesNullAndNothingElse:
    def test_null_becomes_an_empty_object(self):
        assert TypeAdapter(schemas.JsonMetadata).validate_python(None) == {}

    def test_a_real_value_survives(self):
        """The control on the coercion: a validator returning `{}` unconditionally would
        satisfy the test above and silently discard every row's metadata."""
        value = {"gate": "north", "seal": 42}
        assert TypeAdapter(schemas.JsonMetadata).validate_python(value) == value

    def test_an_empty_object_stays_empty(self):
        assert TypeAdapter(schemas.JsonMetadata).validate_python({}) == {}

    def test_it_still_rejects_a_value_that_is_not_an_object(self):
        """Tolerating NULL must not turn the field into `Any`. A string where an object
        belongs is a real error and has to stay one."""
        with pytest.raises(ValidationError):
            TypeAdapter(schemas.JsonMetadata).validate_python("not-an-object")
