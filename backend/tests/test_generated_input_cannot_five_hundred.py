"""A parameter the schema says is unbounded must actually be unbounded.

WHAT THE CONTRACT GATE FOUND (FS-259). The dominant remaining failure in
`test_api_contract.py` is one behaviour: generated input reaching Postgres or Python
unvalidated and surfacing as a **500 where the contract promises a 4xx**. Three of them
were fixed together, and they were not three bugs so much as three instances of the same
one — a declared type that the code cannot actually accept:

  * `skip: int = Query(0, ge=0)` on THIRTEEN endpoints. `OFFSET :skip` binds to a
    Postgres bigint, so an integer above 2**63-1 is not a large offset — it is a value
    asyncpg cannot encode. The schema said "any non-negative integer" and meant
    "any that fits in 64 bits".
  * `upcoming: Optional[int] = Query(None)` on `/maintenance/schedules`. The value is
    added to `now`, so 10508090 is a date past year 9999 and `timedelta` raises
    `OverflowError` before a query runs.
  * `driver_id: str` compared to a UUID column on `/fleet/safety/drivers/{id}`, and the
    same on `PATCH /maintenance/repair-orders/{id}` — the only handler in its file that
    did not call the `_uuid_or_404` guard its siblings all use.

WHY A SWEEP AND NOT FOUR ASSERTIONS. Schemathesis found exactly ONE of the thirteen
unbounded `skip` declarations, because that is the only one it happened to draw a large
enough value for. Fixing that one and raising the ratchet would have been a gain by luck:
the other twelve were equally broken and equally invisible. The sweep below is what makes
the fix systemic — the fourteenth endpoint to declare `skip` is covered before anyone
draws a large value at it.

The per-endpoint tests are kept as well, because the sweep can only see the declaration,
not what the handler does with it.
"""

from __future__ import annotations

import pytest
from fastapi import routing

from app.core.pagination import MAX_OFFSET
from app.main import app
from tests._route_tree import http_routes

#: Parameters whose value becomes a database OFFSET or is otherwise fed to a bigint
#: column. An unbounded one is a 500 waiting for a large enough draw.
_OFFSET_NAMES = {"skip", "offset"}

#: Files another dev owns; their parameters are theirs to bound.
#: `telemetry.py` carries the one remaining unbounded `skip` and is Harsh's.
#:
#: SHARED (FS-590). See `_lane_failures.LANE_ROUTERS` — this list and the one in
#: `test_capped_lists_cannot_grow` had already drifted apart by one entry.
from tests._lane_failures import LANE_ROUTERS as _OTHER_LANES


def _upper_bound(field_info):
    """The `le=` constraint, wherever this pydantic version keeps it.

    Pydantic v2 stores query constraints as `annotated_types` markers in
    `FieldInfo.metadata`, NOT as a `.le` attribute — reading `.le` returns None for a
    bounded parameter as readily as for an unbounded one, so a sweep written against it
    reports every endpoint as broken and is trusted by nobody. Checked against a real
    FieldInfo rather than assumed.
    """
    for marker in getattr(field_info, "metadata", None) or []:
        bound = getattr(marker, "le", None)
        if bound is not None:
            return bound
    return getattr(field_info, "le", None)


def _offset_params():
    """(module, path, param name, its schema) for every declared offset parameter."""
    for route, path, _methods in http_routes(app):
        if not isinstance(route, routing.APIRoute):
            continue
        module = getattr(route.endpoint, "__module__", "?").split(".")[-1]
        for param in route.dependant.query_params:
            if param.name in _OFFSET_NAMES:
                yield module, path, param.name, param.field_info


class TestEveryOffsetDeclaresItsCeiling:
    def test_the_sweep_is_not_vacuous(self):
        """A guard that finds no subject passes for the wrong reason."""
        found = list(_offset_params())
        assert len(found) >= 10, (
            f"only {len(found)} offset parameters found; there were 14 when this was "
            "written. Either the traversal broke or the parameters moved — check "
            "tests/_route_tree.py before adjusting this number."
        )

    def test_no_in_lane_offset_is_unbounded(self):
        unbounded = [
            f"{path} [{module}].{name}"
            for module, path, name, field in _offset_params()
            if module not in _OTHER_LANES and _upper_bound(field) is None
        ]
        assert not unbounded, (
            "these offset parameters declare no upper bound, so a value above the "
            "Postgres bigint ceiling reaches asyncpg and 500s where the schema promises "
            f"a 4xx. Add `le=MAX_OFFSET` (app.core.pagination):\n  "
            + "\n  ".join(sorted(unbounded))
        )

    def test_the_bound_is_the_bigint_ceiling(self):
        """Not a smaller 'sensible' number: at 2**63-1 no request that works today
        starts failing, and only the 500 becomes the documented 422."""
        assert MAX_OFFSET == 2**63 - 1


class TestTheHandlersRejectWhatTheyCannotProcess:
    """The sweep reads declarations; these read behaviour."""

    def test_upcoming_is_bounded_below_the_overflow_point(self):
        """`now + timedelta(days=upcoming)` must not be reachable past year 9999."""
        from datetime import datetime, timedelta, timezone

        route = next(
            r for r, path, _ in http_routes(app)
            if path == "/api/v1/maintenance/schedules"
            and isinstance(r, routing.APIRoute)
            and "GET" in r.methods
        )
        field = next(
            p.field_info for p in route.dependant.query_params if p.name == "upcoming"
        )
        bound = _upper_bound(field)
        assert bound is not None, "unbounded `upcoming` overflows the date range"
        # The declared maximum must actually be addable to now.
        datetime.now(timezone.utc) + timedelta(days=bound)

    def test_the_overflow_is_real_at_the_value_that_found_it(self):
        """Guards the guard: if this stops raising, the bound above is pointless."""
        from datetime import datetime, timedelta, timezone

        with pytest.raises(OverflowError):
            datetime.now(timezone.utc) + timedelta(days=10508090)

    def test_every_repair_order_route_validates_its_path_id(self):
        """`PATCH /repair-orders/{id}` was the one handler in `fleet_logistics` that did
        not, which is why it 500'd on a non-UUID while its siblings answered 404."""
        import inspect

        from app.api import fleet_logistics as fl

        for name in ("get_repair_order", "update_repair_order", "delete_zone",
                     "get_zone", "update_zone", "acknowledge_alert",
                     "get_schedule", "update_schedule"):
            source = inspect.getsource(getattr(fl, name))
            assert "_uuid_or_404" in source, (
                f"{name} compares a path id to a UUID column without validating it; "
                "on Postgres that is an asyncpg type error and a 500, not a 404"
            )

    def test_a_non_uuid_driver_id_is_rejected_before_the_query(self):
        import inspect

        from app.api import fleet_health as fh

        source = inspect.getsource(fh.one_driver_safety)
        assert "UUID(driver_id)" in source, (
            "one_driver_safety compares a free-form str to drivers.id, a UUID column"
        )
