"""`response_model=Dict[str, Any]` satisfies the coverage ratchet and declares nothing (FS-688).

`test_response_model_coverage_ratchet.py` holds `MAX_UNDECLARED = 52` and asks one question of
each route: `getattr(route, "response_model", None) is None`. Any model passes. So the cheapest
way to reduce that number is not to write a schema — it is to write

    response_model=Dict[str, Any]

which counts as declared, produces an OpenAPI `object` with no properties, hands the generated
SDK an untyped blob, and gives every downstream guard that reads declared models
(`test_response_models_match_their_tables.py`, `test_declared_models_do_not_drop_fields.py`)
nothing to check.

That is rule 187 exactly: **ask what the cheapest reduction of a ratchet would do.** Here it
buys the number without buying the contract, and the route then *looks* documented, which is
worse than being visibly undocumented.

**23 routes are in that state today.** This file is not an accusation — several are legitimately
dynamic and are registered below with reasons. It exists so the count is visible, can only
shrink, and cannot be added to silently. The existing ratchet keeps counting what it counts;
this keeps a different list, which is why `test_no_two_guards_keep_the_same_list.py` is content.

WHERE IT BITES HARDEST. `GET /transportation/drivers` answers `List[Dict[str, Any]]` while
`DriverResponse` exists and is used by the single-driver route beside it. A client reading the
schema learns that the list endpoint returns objects, and nothing more.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _route_tree import flatten  # noqa: E402

#: Model spellings that declare no fields. `str()` of the annotation, because these are typing
#: constructs rather than classes and comparing identity misses `dict` vs `Dict[str, Any]`.
PERMISSIVE = {
    "typing.Dict[str, typing.Any]",
    "typing.List[typing.Dict[str, typing.Any]]",
    "typing.Any",
    "dict",
    "list",
    "<class 'dict'>",
    "<class 'list'>",
}

#: Routes whose response genuinely has no fixed shape, with the reason. Everything not named
#: here is debt: a route that could describe itself and does not.
DELIBERATELY_DYNAMIC = {
    "GET /api/v1/feature-flags/{key}": "a flag's value is arbitrary client-supplied JSON",
    "POST /api/v1/feature-flags/": "same value, on the way in",
    "PUT /api/v1/feature-flags/{key}": "same value, on the way in",
    "POST /api/v1/simulation/monte-carlo": "the result shape follows the scenario the caller submits",
    "GET /api/v1/simulation/fleet-summary": "aggregates whichever scenario keys the run produced",
}

#: The measured figure. ONLY EVER SHRINKS — and the way down is a schema, not an entry here.
MAX_PERMISSIVE = 23


def _permissive_routes() -> list[str]:
    from app.main import app

    found = []
    for route, prefix in flatten(app.routes):
        model = getattr(route, "response_model", None)
        if model is None or str(model) not in PERMISSIVE:
            continue
        methods = sorted(getattr(route, "methods", []) or ["?"])
        verb = next((m for m in methods if m in ("GET", "POST", "PUT", "PATCH", "DELETE")), methods[0])
        found.append(f"{verb} {prefix + getattr(route, 'path', '')}")
    return sorted(found)


class TestTheMeasurementIsReal:
    def test_it_finds_typed_routes_too(self):
        """Vacuity. If `response_model` stopped being readable every route would look
        permissive, or none would, and both readings are worthless."""
        from app.main import app

        typed = [
            r
            for r, _p in flatten(app.routes)
            if getattr(r, "response_model", None) is not None
            and str(getattr(r, "response_model")) not in PERMISSIVE
        ]
        assert len(typed) > 300, f"only {len(typed)} typed response models found"

    def test_the_permissive_spellings_are_recognised(self):
        """`dict` and `Dict[str, Any]` are the same claim written two ways, and an earlier
        draft that compared classes rather than strings saw only one of them."""
        import typing

        assert str(typing.Dict[str, typing.Any]) in PERMISSIVE
        assert str(dict) in PERMISSIVE

    def test_every_registered_route_still_exists(self):
        """A register naming a route that has been renamed is an exemption nobody can audit."""
        live = set(_permissive_routes())
        stale = sorted(set(DELIBERATELY_DYNAMIC) - live)
        assert not stale, (
            f"{stale} are registered as deliberately dynamic and no longer answer with a "
            f"permissive model — delete the entries rather than leaving them to rot"
        )


def test_the_permissive_surface_only_shrinks():
    found = _permissive_routes()
    assert len(found) <= MAX_PERMISSIVE, (
        f"{len(found)} routes declare a response model that describes nothing, up from "
        f"{MAX_PERMISSIVE}.\n{found}\n\n"
        f"`Dict[str, Any]` satisfies the coverage ratchet without adding a contract: the "
        f"OpenAPI schema says `object` with no properties and the generated SDK gets an "
        f"untyped blob. Declare the real shape, or register the route in "
        f"DELIBERATELY_DYNAMIC with the reason its response has no fixed shape."
    )


def test_a_route_with_a_real_model_available_is_named():
    """The clearest instance, asserted by itself so it does not disappear into a count.

    `GET /transportation/drivers` returns `List[Dict[str, Any]]` while `DriverResponse`
    exists and describes most of those rows. This test fails the day somebody fixes it,
    which is the point — a to-do with an expiry rather than a permanent exemption.

    AND IT IS NOT A ONE-LINER, which is worth knowing before starting. The handler dumps
    `DriverResponse` and then adds seven derived keys — `carrierName`, `currentVehicleId`,
    `currentShipmentId`, `endorsements`, `licenseExpiry`, `hosDriveHoursRemaining`,
    `hosDutyHoursRemaining` — in **camelCase**, while the model's own keys come out
    snake_case (there is no alias generator on `DriverResponse`). The client reconciles the
    two through `registerTransform('/api/v1/transportation')`.

    So the model needed here is `DriverResponse` plus those seven, spelled exactly as the
    handler spells them. Declare it with any of them missing and FastAPI **filters the
    missing one out of the response** — the "declared field that is dropped" defect this
    codebase has fixed more than once, and it would land on `hosDriveHoursRemaining`, which
    the compliance tab reads to count DOT violations."""
    assert "GET /api/v1/transportation/drivers" in _permissive_routes(), (
        "the drivers list now declares a real model — delete this test and lower "
        "MAX_PERMISSIVE, which is the outcome it was written to provoke"
    )


@pytest.mark.parametrize("route", sorted(DELIBERATELY_DYNAMIC))
def test_the_registered_reasons_are_stated(route: str):
    assert DELIBERATELY_DYNAMIC[route].strip(), f"{route} is registered with no reason"
