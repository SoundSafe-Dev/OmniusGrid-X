"""No API response model may be stricter than the columns behind it — platform-wide.

THE DEFECT THIS GENERALISES. `ERPIntegrationResponse` declared `sync_schedule`,
`erp_type` and `sync_frequency_minutes` as required while all three are nullable on
`integration_configurations`. A row holding NULL in any of them could not be serialised
at all: pydantic raised inside the handler and FastAPI returned 500 — for create, list,
get AND update, because all four build the same model. The 500 named a validation error
in our schema rather than the data, so nobody would think to look at the row.

`tests/test_erp_response_schema.py` guards that with a hand-maintained mapping of ERP
models. This file does the same thing for **every** response model in `app/api/` by
discovering the pairs, so a new router cannot introduce the bug without being noticed.

WHAT IT DOES NOT CLAIM. It only inspects models it can confidently pair with an ORM
model by name (`FooResponse` -> `Foo`) and fields whose names match a column. A handler
that synthesises a value (`configuration.get("x", "")`) is out of scope, because there
the handler is the guarantee. `test_no_pair_is_vacuous` keeps the discovery honest: if
the pairing ever finds nothing, the whole file would pass while checking zero fields.

WHEN THIS WAS WRITTEN IT FOUND NOTHING, and that is the point of recording it. The ERP
models were the only offenders and were already fixed. Running it now proves the rest of
the API is clean rather than untested, and it fails the moment that stops being true.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import types
import typing
import warnings
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel
from sqlalchemy.inspection import inspect as sa_inspect

import app.api as api_pkg
import app.db.models as orm_models

RESPONSE_SUFFIXES = ("Response", "Out", "Read", "Detail", "Item")


def is_optional(annotation: Any) -> bool:
    """Does this annotation admit None?

    MUST handle both spellings. `Optional[str]` produces `typing.Union`, while the PEP
    604 form `str | None` produces `types.UnionType` — a different object. An earlier
    version of this check only tested `typing.Union`, so every `X | None` field was
    misread as required.

    That is not hypothetical: it made a scan of the whole API report 8 defects that did
    not exist, and it would have made the ERP guard fail the moment someone wrote a
    response field in modern syntax. `test_the_detector_handles_both_spellings` below
    exists because this helper is load-bearing — if it is wrong, every assertion in this
    file is meaningless in one direction or the other.
    """
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        return type(None) in typing.get_args(annotation)
    return annotation is type(None)


def _orm_classes() -> Dict[str, Any]:
    return {
        name: obj
        for name, obj in vars(orm_models).items()
        if isinstance(obj, type) and hasattr(obj, "__tablename__")
    }


def _columns(orm_class) -> Dict[str, Any]:
    try:
        return {c.key: c for c in sa_inspect(orm_class).columns}
    except Exception:  # noqa: BLE001 - not every mapped class inspects cleanly
        return {}


def _discover() -> List[Tuple[str, Any, Any]]:
    """(module, response model, ORM model) for every pair resolvable by name."""
    orm = _orm_classes()
    found: List[Tuple[str, Any, Any]] = []

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for module_info in pkgutil.iter_modules(api_pkg.__path__):
            try:
                module = importlib.import_module(f"app.api.{module_info.name}")
            except Exception:  # noqa: BLE001 - an unimportable router is another test's problem
                continue
            for name, obj in vars(module).items():
                if not (isinstance(obj, type) and issubclass(obj, BaseModel)):
                    continue
                if obj is BaseModel or obj.__module__ != module.__name__:
                    continue
                if not name.endswith(RESPONSE_SUFFIXES):
                    continue
                target = orm.get(re.sub(rf"({'|'.join(RESPONSE_SUFFIXES)})$", "", name))
                if target is not None:
                    found.append((module_info.name, obj, target))
    return found


PAIRS = _discover()


def _offenders() -> List[str]:
    """Fields that are required in the response but can genuinely be NULL on the row.

    A column with a default — Python-side or server-side — is excluded: the ORM or the
    database fills it, so a required response field is safe. Only a nullable column with
    NO default can actually hand pydantic a None.
    """
    bad: List[str] = []
    for module_name, response_model, orm_class in PAIRS:
        columns = _columns(orm_class)
        for field_name, field in response_model.model_fields.items():
            column = columns.get(field_name)
            if column is None or not column.nullable:
                continue
            if column.server_default is not None or column.default is not None:
                continue
            if field.is_required() and not is_optional(field.annotation):
                bad.append(
                    f"{module_name}.{response_model.__name__}.{field_name} "
                    f"(column {orm_class.__name__}.{field_name} is nullable with no default)"
                )
    return bad


class TestTheDetectorItself:
    """This helper decides every other assertion, so it is tested first."""

    def test_the_detector_handles_both_spellings(self):
        assert is_optional(typing.Optional[str]), "Optional[str] not recognised"
        assert is_optional(str | None), (
            "PEP 604 `str | None` not recognised — it produces types.UnionType, not "
            "typing.Union. Getting this wrong misreads every modern annotation as "
            "required and manufactures defects that do not exist."
        )
        assert is_optional(typing.Union[int, None])
        assert is_optional(int | str | None)

    def test_the_detector_rejects_genuinely_required_annotations(self):
        assert not is_optional(str)
        assert not is_optional(int)
        assert not is_optional(typing.Union[int, str])
        assert not is_optional(List[str])


class TestNoResponseModelIsStricterThanItsColumns:
    def test_no_offenders(self):
        offenders = _offenders()
        assert not offenders, (
            "A required response field over a nullable column means a valid row cannot "
            "be serialised — pydantic raises inside the handler and FastAPI returns 500, "
            "naming a validation error in our schema rather than the data:\n  "
            + "\n  ".join(offenders)
        )

    def test_no_pair_is_vacuous(self):
        """Guards the guard. If discovery finds nothing — a rename, a moved module, a
        broken import — every assertion above passes while checking zero fields, which
        is exactly how the original bug survived."""
        assert len(PAIRS) >= 10, (
            f"only {len(PAIRS)} response/ORM pairs discovered; the sweep is not "
            f"covering the API and would pass vacuously"
        )

    def test_at_least_one_paired_column_is_nullable_without_a_default(self):
        """The other half of not-vacuous: if no discovered column could ever be NULL,
        `test_no_offenders` proves nothing."""
        candidates = [
            f"{orm_class.__name__}.{name}"
            for _m, _r, orm_class in PAIRS
            for name, column in _columns(orm_class).items()
            if column.nullable and column.server_default is None and column.default is None
        ]
        assert candidates, (
            "no paired column is nullable-without-default, so the sweep has nothing to "
            "catch and would pass regardless"
        )


class TestCoverageIsVisible:
    def test_report_what_is_actually_covered(self, capsys):
        """Not an assertion so much as a record. A guard whose reach is invisible drifts
        without anyone noticing which routers it stopped covering."""
        modules = sorted({m for m, _r, _o in PAIRS})
        fields = sum(len(r.model_fields) for _m, r, _o in PAIRS)
        with capsys.disabled():
            print(
                f"\n  response-schema sweep: {len(PAIRS)} model pairs across "
                f"{len(modules)} routers, {fields} fields compared"
            )
        assert fields > 50
