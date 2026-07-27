"""A response model must never be stricter than the columns behind it.

THE DEFECT THIS GUARDS. `ERPIntegrationResponse` declared `sync_schedule: str`,
`erp_type: str` and `sync_frequency_minutes: int` as required, while all three are
nullable on `integration_configurations` (the last has only a Python-side default,
which does not apply to rows written by anything but the ORM).

A row holding NULL in any of them therefore could not be serialised at all: pydantic
raised inside the handler and FastAPI returned 500. And not for one endpoint —
create, list, get and update all build this model — so a single NULL made an
integration simultaneously unreadable and uneditable. The 500 names a validation
error, pointing at our schema rather than at the data, so nobody would look at the
row.

Rows like that are easy to produce: the demo seeder, a migration backfill, a fixture,
or any insert that is not the create endpoint (whose *request* model happens to
default `sync_schedule`). Found by a cross-platform test the first time it created an
integration the way anything other than the API does.

THE RULE. If a column is nullable, the response field must be optional. The reverse
is fine — a response may be stricter about presence than the database is about
storage only when the handler guarantees a value (a literal, or `or ""`).
"""

from __future__ import annotations

import types
import typing
from typing import Any, Dict, Optional, Tuple, Union

import pytest

from app.api.erp_integrations import ERPIntegrationResponse, SyncStatusResponse
from app.db.models import ERPSyncStatus, IntegrationConfiguration


def _is_optional(annotation: Any) -> bool:
    """Does this annotation admit None?

    MUST handle both spellings. `Optional[str]` produces `typing.Union`; the PEP 604
    form `str | None` produces `types.UnionType`, a different object. This originally
    checked only `typing.Union`, so a field written in the modern syntax was misread as
    REQUIRED — which would have failed this guard for a model that was perfectly
    correct, and sent someone "fixing" a non-bug.

    Found while generalising this sweep across the whole API: the same flaw made that
    scan report 8 defects that did not exist.
    """
    origin = typing.get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return type(None) in typing.get_args(annotation)
    return annotation is type(None)


def _field_is_required(model, name: str) -> bool:
    field = model.model_fields[name]
    return field.is_required() and not _is_optional(field.annotation)


def _column_is_nullable(orm_model, name: str) -> Optional[bool]:
    column = getattr(orm_model, name, None)
    if column is None or not hasattr(column, "property"):
        return None
    columns = getattr(column.property, "columns", None)
    if not columns:
        return None
    return bool(columns[0].nullable)


#: (response model, ORM model, {response field: column name})
#:
#: Only fields read STRAIGHT off the row. Fields the handler synthesises
#: (`auth_type` and `base_url` come from `configuration.get(..., "")`, which cannot
#: be None) are excluded, because there the handler is the guarantee.
SCHEMA_PAIRS: Tuple[Tuple[Any, Any, Dict[str, str]], ...] = (
    (
        ERPIntegrationResponse,
        IntegrationConfiguration,
        {
            "integration_name": "integration_name",
            "erp_type": "erp_type",
            "erp_version": "erp_version",
            "is_active": "is_active",
            "sync_schedule": "sync_schedule",
            "sync_frequency_minutes": "sync_frequency_minutes",
            "last_successful_sync": "last_successful_sync",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    ),
    (
        SyncStatusResponse,
        ERPSyncStatus,
        {
            "entity_type": "entity_type",
            "last_sync_at": "last_sync_at",
            "last_sync_status": "last_sync_status",
            "records_synced": "records_synced",
            "records_failed": "records_failed",
            "sync_duration_seconds": "sync_duration_seconds",
            "updated_at": "updated_at",
        },
    ),
)


def _pairs():
    for response_model, orm_model, mapping in SCHEMA_PAIRS:
        for response_field, column_name in mapping.items():
            yield response_model, orm_model, response_field, column_name


@pytest.mark.parametrize(
    "response_model,orm_model,response_field,column_name",
    list(_pairs()),
    ids=[f"{r.__name__}.{f}" for r, _o, f, _c in _pairs()],
)
def test_a_nullable_column_has_an_optional_response_field(
    response_model, orm_model, response_field, column_name
):
    nullable = _column_is_nullable(orm_model, column_name)
    if nullable is None:
        pytest.skip(f"{orm_model.__name__}.{column_name} is not a plain column")

    if nullable and _field_is_required(response_model, response_field):
        pytest.fail(
            f"{response_model.__name__}.{response_field} is required, but "
            f"{orm_model.__name__}.{column_name} is nullable. A row holding NULL "
            f"there cannot be serialised, so EVERY endpoint returning this model "
            f"answers 500 for that row — with a validation error that points at the "
            f"schema instead of the data."
        )


class TestTheGuardIsNotVacuous:
    def test_the_mapped_fields_actually_exist_on_both_sides(self):
        """A typo in the mapping would silently reduce coverage to nothing."""
        for response_model, orm_model, mapping in SCHEMA_PAIRS:
            for response_field, column_name in mapping.items():
                assert response_field in response_model.model_fields, (
                    f"{response_model.__name__} has no field {response_field!r}"
                )
                assert hasattr(orm_model, column_name), (
                    f"{orm_model.__name__} has no column {column_name!r}"
                )

    def test_at_least_one_mapped_column_is_actually_nullable(self):
        """If none were, the parametrized test above would pass without checking
        anything — which is exactly how this bug survived."""
        nullable = [
            (o.__name__, c)
            for _r, o, m in SCHEMA_PAIRS
            for c in m.values()
            if _column_is_nullable(o, c)
        ]
        assert nullable, "no mapped column is nullable; the guard proves nothing"

    def test_the_optionality_detector_works(self):
        """The helper is the load-bearing part; a broken detector makes every
        assertion above pass — or fail on correct code."""
        assert _is_optional(Optional[str])
        assert _is_optional(Union[str, None])
        assert _is_optional(str | None), (
            "PEP 604 syntax not recognised; a correctly-optional field would be "
            "reported as a defect"
        )
        assert not _is_optional(str)
        assert not _is_optional(int)


class TestTheSpecificRegression:
    @pytest.mark.parametrize(
        "field", ["sync_schedule", "erp_type", "sync_frequency_minutes"]
    )
    def test_the_three_fields_that_caused_500s_are_optional(self, field):
        """Named explicitly so a future "tidy-up" that re-tightens them fails with
        the reason rather than with a mystery."""
        assert not _field_is_required(ERPIntegrationResponse, field), (
            f"{field} is required again; a NULL there returns 500 from create, list, "
            f"get AND update"
        )

    def test_a_row_with_nulls_serialises(self):
        """The end of the story: the exact shape that used to raise."""
        model = ERPIntegrationResponse(
            id="00000000-0000-0000-0000-000000000001",
            integration_name="seeded-by-something-other-than-the-api",
            erp_type=None,
            erp_version=None,
            auth_type="",
            base_url="",
            is_active=True,
            sync_schedule=None,
            sync_frequency_minutes=None,
            last_successful_sync=None,
            created_at=None,
            updated_at=None,
        )
        assert model.sync_schedule is None
