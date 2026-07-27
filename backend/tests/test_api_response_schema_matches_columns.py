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

THIS FILE HAS BEEN WRONG TWICE, IN OPPOSITE DIRECTIONS, and both are worth knowing
because each looked like a reasonable simplification at the time.

**It under-reported, and claimed the whole API was clean.** Two exclusions were at
fault: it skipped any column carrying a PYTHON-side ORM default — which fires only for
rows written through SQLAlchemy, so a migration, a seeder or a raw INSERT still leaves
NULL — and it required `obj.__module__ == module.__name__`, which skipped every response
model a router imports from `app/models/schemas.py`. A raw-inserted dock door then
returned a live 500: *"equipment_capabilities: Input should be a valid dictionary"*.

**Then it over-reported, by a factor of three.** Corrected, it flagged 158 fields — but
it was reading `column.server_default` off the ORM metadata, and **109 of those columns
do have a database default**, added by migration 044 and never mirrored back into the ORM
declaration. The application's opinion of the schema is not the schema.

So it now reads `information_schema` from the migrated database. The true count was 49:
39 given server defaults by migration 050, and 10 nullable columns with no default
anywhere, whose response fields now mirror them. **Zero remain**, and the 158-entry
baseline is gone — most of it described columns that were never at risk.

WHAT IT DOES NOT CLAIM. It only inspects models it can pair with an ORM model by name
(`FooResponse` -> `Foo`) and fields whose names match a column. A handler that
synthesises a value (`configuration.get("x", "")`) is out of scope, because there the
handler is the guarantee. The vacuity tests keep the discovery honest: if the pairing
ever finds nothing, the file would pass while checking zero fields.
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
    seen: set = set()

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
                # Deliberately NOT `obj.__module__ != module.__name__`. That skipped
                # every response model a router imports from `app/models/schemas.py`,
                # which is where a large share of them live — including
                # `DockDoorResponse`, whose live 500 this file had reported as clean.
                # Dedup below keeps a shared model from being checked once per router.
                if obj is BaseModel:
                    continue
                if not name.endswith(RESPONSE_SUFFIXES):
                    continue
                target = orm.get(re.sub(rf"({'|'.join(RESPONSE_SUFFIXES)})$", "", name))
                if target is not None and (obj, target) not in seen:
                    seen.add((obj, target))
                    found.append((module_info.name, obj, target))
    return found


PAIRS = _discover()


def _real_column_defaults(sync_url: str) -> Dict[str, Any]:
    """{"table.column": default expression} straight from the migrated database.

    THE SCHEMA, NOT THE ORM'S OPINION OF IT. Reading `column.server_default` off the
    model reports what the declaration says, and the two diverge: migration 044 added
    `DEFAULT NOW()` to timestamp columns across 30 tables without mirroring it back into
    the ORM. Trusting the model flagged 158 fields, of which 109 were columns the
    database already defaults and no INSERT can leave NULL.
    """
    import psycopg2

    connection = psycopg2.connect(sync_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name, column_default "
                "FROM information_schema.columns WHERE table_schema = 'public'"
            )
            return {f"{t}.{c}": d for t, c, d in cursor.fetchall()}
    finally:
        connection.close()


def _offenders(real_defaults: Dict[str, Any]) -> List[str]:
    """Fields required in the response that a real row can genuinely hand a None.

    Safe means the DATABASE fills the column. A Python-side ORM default does not count:
    it fires only for rows written through SQLAlchemy, so a migration, a seeder or any
    raw INSERT still writes NULL.

    A pydantic default does not rescue it either — the ORM passes the attribute's
    explicit None rather than omitting the field, so the default never applies and
    validation runs against None. Hence the test is `is_optional` on the annotation, not
    `is_required`: a field with a default but a non-optional type still fails.
    """
    bad: List[str] = []
    for module_name, response_model, orm_class in PAIRS:
        columns = _columns(orm_class)
        table = getattr(orm_class, "__tablename__", None)
        for field_name, field in response_model.model_fields.items():
            column = columns.get(field_name)
            if column is None or not column.nullable:
                continue
            if real_defaults.get(f"{table}.{field_name}") is not None:
                continue
            if not is_optional(field.annotation):
                bad.append(
                    f"{module_name}.{response_model.__name__}.{field_name} "
                    f"(column {table}.{field_name} is nullable with no server default)"
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
    def test_no_offenders(self, admin_sync_url):
        """Checked against the MIGRATED SCHEMA, not the ORM's declaration of it.

        No baseline: the true count is zero. The 158-entry list this replaced was
        mostly an artifact of asking the model instead of the database — 109 of those
        columns are defaulted by migration 044, which the ORM never mirrored.
        """
        offenders = _offenders(_real_column_defaults(admin_sync_url))
        assert not offenders, (
            "A required response field over a nullable column with no SERVER default "
            "means a valid row cannot be serialised — pydantic raises inside the "
            "handler and FastAPI returns 500, naming a validation error in our schema "
            "rather than the data. A Python-side ORM default does not prevent this: it "
            "fires only for rows written through SQLAlchemy.\n  " + "\n  ".join(offenders)
        )

    def test_the_check_reflects_the_database_not_the_orm(self, admin_sync_url):
        """The specific mistake that inflated this file's count threefold.

        `assets.created_at` carries a Python-side `default=utcnow` and NO
        `server_default` in the ORM, yet migration 044 gave it `DEFAULT NOW()`. If the
        check ever reads the model again, this column reappears as an offender.
        """
        real = _real_column_defaults(admin_sync_url)
        assert real.get("assets.created_at"), (
            "assets.created_at has no database default — migration 044 should have set "
            "one; the schema, not the ORM, is what this file must read"
        )
        from app.db.models import Asset

        assert sa_inspect(Asset).columns["created_at"].server_default is None, (
            "the ORM now declares a server_default for assets.created_at, so this test "
            "no longer demonstrates the divergence it exists to pin"
        )

    def test_no_pair_is_vacuous(self):
        """Guards the guard. If discovery finds nothing — a rename, a moved module, a
        broken import — every assertion above passes while checking zero fields, which
        is exactly how the original bug survived."""
        assert len(PAIRS) >= 10, (
            f"only {len(PAIRS)} response/ORM pairs discovered; the sweep is not "
            f"covering the API and would pass vacuously"
        )

    def test_at_least_one_paired_column_could_still_be_null(self, admin_sync_url):
        """The other half of not-vacuous: if every discovered column were defaulted by
        the database, `test_no_offenders` would pass no matter what the models said.

        Against the real schema, not the ORM — the same correction as the main check.
        """
        real = _real_column_defaults(admin_sync_url)
        candidates = [
            f"{orm_class.__tablename__}.{name}"
            for _m, _r, orm_class in PAIRS
            for name, column in _columns(orm_class).items()
            if column.nullable
            and real.get(f"{orm_class.__tablename__}.{name}") is None
        ]
        assert candidates, (
            "no paired column is nullable-without-a-server-default, so the sweep has "
            "nothing to catch and would pass regardless"
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
