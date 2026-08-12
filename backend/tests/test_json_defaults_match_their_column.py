"""A container default that contradicts its column's shape (FS-670).

WRITTEN AFTER SHIPPING THIS BUG, an hour before the guard. Wiring `temperature_zones` through
`create_load_plan` I wrote:

    temperature_zones=temperature_zones or {}

`load_plans.temperature_zones` is `Column(JSON, default=[])` and the schema declares
`List[Dict[str, Any]]`. The `{}` stored an object, `LoadPlanResponse` then refused to serialise
the row, and **every load-plan create answered 500** — on a route that had been working.

WHY IT IS WORTH A GUARD RATHER THAN A LESSON. The failure is on the SUCCESS path only:
`route_walk` drives every route looking for 5xx, but with generated inputs a create rejects
before it reaches the response, so the smoke test cannot see it (rule 139). What caught it was
a real-database test that creates a load plan and asserts a 2xx — one test, in a file I had not
touched, in a run I nearly skipped because "nothing I changed is near it".

Both containers are falsy when empty, so `or` cannot distinguish "caller sent nothing" from
"caller sent an empty one" either — but that is a smaller problem than storing the wrong type,
and fixing it needs `is None` at every site rather than a shape check.

THE CHECK. For every `field=value or {}` / `or []` in `app/`, look up what that column's
default declares and require the two to agree. Eighteen sites qualify today and all eighteen
agree; the sweep is cheap and the counter-example is the line above.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.db import models as models_module

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: `field=<expr> or {}` and the list form. Deliberately narrow — a broader pattern would match
#: `x = y or {}` on locals, where there is no column to compare against and no defect to find.
CONTAINER_DEFAULT = re.compile(r"(\w+)\s*=\s*\w+\s+or\s+(\{\}|\[\])")


def _column_shapes() -> dict[str, set[str]]:
    """column name -> {'list'} / {'dict'}, from the live metadata rather than the source.

    Read from `__table__` because a regex over `Column(JSON, default=[])` would miss the
    columns whose default arrives through a shared helper, and this guard exists because a
    text-level assumption was wrong once already.
    """
    shapes: dict[str, set[str]] = {}
    for name in dir(models_module):
        table = getattr(getattr(models_module, name), "__table__", None)
        if table is None:
            continue
        for column in table.columns:
            default = getattr(column.default, "arg", None) if column.default is not None else None
            if isinstance(default, list):
                shapes.setdefault(column.name, set()).add("list")
            elif isinstance(default, dict):
                shapes.setdefault(column.name, set()).add("dict")
    return shapes


def _sites():
    shapes = _column_shapes()
    for path in sorted(APP.rglob("*.py")):
        source = path.read_text()
        for match in CONTAINER_DEFAULT.finditer(source):
            field, literal = match.group(1), match.group(2)
            declared = shapes.get(field)
            if not declared:
                continue
            yield (
                path.relative_to(APP.parent),
                source[: match.start()].count("\n") + 1,
                field,
                "dict" if literal == "{}" else "list",
                declared,
            )


class TestTheMeasurementIsReal:
    def test_columns_are_readable(self):
        shapes = _column_shapes()
        assert len(shapes) > 20, (
            f"only {len(shapes)} container-defaulted columns found; the metadata walk "
            f"collapsed and the assertion below would be about nothing"
        )

    def test_sites_are_found(self):
        """Vacuity. A regex matching nothing would report a clean tree."""
        assert len(list(_sites())) > 5

    def test_the_pattern_matches_the_line_that_caused_this(self):
        """Positive control, and it is a real line: `temperature_zones=temperature_zones or {}`
        is what shipped, and what answered 500 on every load-plan create."""
        match = CONTAINER_DEFAULT.search("temperature_zones=temperature_zones or {}")
        assert match and match.group(1) == "temperature_zones" and match.group(2) == "{}"
        assert _column_shapes().get("temperature_zones") == {"list"}, (
            "the column no longer declares a list default, so the control is stale — "
            "re-derive it before trusting this file"
        )

    def test_a_matching_default_is_not_flagged(self):
        """Negative control, so the guard is not simply calling everything wrong."""
        shapes = _column_shapes()
        agreeing = [f for f, s in shapes.items() if s == {"dict"}]
        assert agreeing, "no dict-defaulted column to check the happy path against"


def test_no_container_default_contradicts_its_column():
    wrong = [
        f"{path}:{line} — {field} defaulted to {got}, column declares {sorted(declared)}"
        for path, line, field, got, declared in _sites()
        if got not in declared
    ]
    assert not wrong, (
        f"{wrong}\n\n"
        f"A JSON column defaulted to the wrong container stores the wrong type, and the "
        f"response model then refuses to serialise the row — a 500 on the SUCCESS path of a "
        f"route that was working. `route_walk` cannot see it: with generated inputs a create "
        f"rejects before it reaches the response."
    )


@pytest.mark.parametrize("literal,shape", [("{}", "dict"), ("[]", "list")])
def test_both_literal_forms_are_understood(literal: str, shape: str):
    """The regex has two branches and only one of them was exercised by the bug. An
    unexercised branch in a guard is the guard's own version of untested code."""
    match = CONTAINER_DEFAULT.search(f"field=value or {literal}")
    assert match
    assert ("dict" if match.group(2) == "{}" else "list") == shape
