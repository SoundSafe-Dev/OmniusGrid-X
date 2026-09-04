"""Every pagination parameter must declare a lower bound.

A `limit`/`offset`/`skip` declared as a bare `int` accepts a negative number, which
FastAPI passes straight through to the query, and Postgres rejects at execution time:

    asyncpg.exceptions.InvalidRowCountInResultOffsetClauseError
    asyncpg.exceptions.InvalidRowCountInLimitClauseError

That surfaces as a **500**. It is a client error — the request was malformed — and a 500
tells the caller the opposite: that the server broke and the request might succeed on
retry, when it never will. It also puts a non-incident into error tracking.

Found by the API contract suite, which generates negative integers for any unconstrained
integer parameter: 25 declarations across 5 routers were unbounded while 47 elsewhere
already used `Query(..., ge=...)`. The convention existed; these had drifted from it.

This guard is written against the generated OpenAPI schema rather than the source, so it
sees what the API actually publishes — including routes added later, and routes whose
parameters come from a shared dependency rather than a literal in the signature.
"""

import pytest

from app.main import app

#: Parameter names that index into a result set. A negative value for any of them is
#: meaningless and reaches the database as invalid SQL.
PAGINATION_NAMES = {"limit", "offset", "skip"}


def _integer_pagination_params():
    """Yield (path, method, param) for every integer pagination parameter."""
    spec = app.openapi()
    for path, operations in spec.get("paths", {}).items():
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            for param in operation.get("parameters", []):
                if param.get("name") not in PAGINATION_NAMES:
                    continue
                schema = param.get("schema") or {}
                # A nullable/optional parameter is expressed as anyOf; take the integer arm.
                arms = schema.get("anyOf") or [schema]
                for arm in arms:
                    if arm.get("type") == "integer":
                        yield path, method.upper(), param, arm
                        break


def test_the_sweep_finds_pagination_parameters_at_all():
    """A guard that inspects nothing passes for the wrong reason.

    If the schema fails to build, or the parameter names change, every assertion below
    would vacuously pass while the API went unchecked.
    """
    found = list(_integer_pagination_params())
    assert len(found) > 30, (
        f"only {len(found)} integer pagination parameters found in the OpenAPI schema; "
        "this guard is probably inspecting nothing"
    )


def test_every_pagination_parameter_declares_a_lower_bound():
    offenders = []
    for path, method, param, arm in _integer_pagination_params():
        if "minimum" not in arm and "exclusiveMinimum" not in arm:
            offenders.append(f"{method} {path} -> {param['name']}")

    assert not offenders, (
        "these pagination parameters accept negative values, which reach Postgres as "
        "invalid SQL and surface as a 500 instead of a 422:\n  "
        + "\n  ".join(sorted(offenders))
        + "\n\nDeclare the bound the rest of the API already uses, e.g. "
        "`limit: int = Query(50, ge=1, ...)` or `offset: int = Query(0, ge=0, ...)`."
    )


@pytest.mark.parametrize("name,floor", [("limit", 0), ("offset", 0), ("skip", 0)])
def test_the_bounds_are_the_right_way_round(name: str, floor: int):
    """A bound exists AND is sane — `ge=-1` would satisfy the test above and still crash.

    The floor is 0 for all three, INCLUDING limit, which is not the convention most of
    this API uses. `Query(50, ge=1, ...)` is the house style and what the fixed routers
    now use, but three registry routes declare `ge=0` and that is not a defect: `LIMIT 0`
    is valid SQL that returns no rows. Only a NEGATIVE value reaches Postgres as invalid
    SQL, which is the failure this guard exists to prevent.

    Asserting the convention here instead would fail the build over a style difference in
    another lane's routes, using a test whose stated subject is crashes. A guard that
    fails for a reason other than the one it advertises is how guards lose their meaning.
    """
    wrong = []
    for path, method, param, arm in _integer_pagination_params():
        if param["name"] != name:
            continue
        minimum = arm.get("minimum", arm.get("exclusiveMinimum"))
        if minimum is None or minimum < floor:
            wrong.append(f"{method} {path} -> {name} minimum={minimum}")

    assert not wrong, (
        f"`{name}` must not go below {floor}:\n  " + "\n  ".join(sorted(wrong))
    )


# FS-898/901. 41 collection endpoints across my lanes returned an unbounded `List[...]`
# with no `limit`/`offset` at all -- a different defect from the one above (a parameter
# that exists but has no floor). Named by (method, path) rather than counted, for the
# same reason NOT_RERUNNABLE in test_every_migration_can_be_rerun_realdb.py is named: a
# count can be satisfied by deleting a route from this list, which would make the guard
# pass while fixing nothing. Every entry here was measured and paginated in this pass;
# a route added to this list without also being paginated is a regression, not a
# registration.
PAGINATED_IN_FS_898 = {
    ("GET", "/api/v1/fleet/sites"),
    ("GET", "/api/v1/fleet/workcells"),
    ("GET", "/api/v1/fleet/tags"),
    ("GET", "/api/v1/fleet/groups"),
    ("GET", "/api/v1/fleet/cohorts"),
    ("GET", "/api/v1/transportation/carriers"),
    ("GET", "/api/v1/transportation/drivers"),
    ("GET", "/api/v1/transportation/routes"),
    ("GET", "/api/v1/yard/dock/doors"),
    ("GET", "/api/v1/yard/detention-alerts"),
    ("GET", "/api/v1/edge/fleet"),
    ("GET", "/api/v1/geotab/devices"),
    ("GET", "/api/v1/geotab/devices/{device_id}/trips"),
    ("GET", "/api/v1/assets/types/"),
    ("GET", "/api/v1/shop-floor/downtime/open"),
    ("GET", "/api/v1/fleet/maintenance-windows"),
    ("GET", "/api/v1/notifications/subscriptions"),
}


def _has_limit_and_offset(path: str, method: str) -> bool:
    spec = app.openapi()
    operation = spec.get("paths", {}).get(path, {}).get(method.lower())
    if not operation:
        return False
    names = {p.get("name") for p in operation.get("parameters", [])}
    return {"limit", "offset"} <= names


class TestTheFS898RoutesStayPaginated:
    def test_the_list_is_not_empty(self):
        """A guard that checks nothing passes for the wrong reason."""
        assert len(PAGINATED_IN_FS_898) >= 15

    def test_every_named_route_still_exists(self):
        """If a route was renamed or removed, this list is stale -- and a stale entry
        makes the next test vacuous for that route rather than failing loudly."""
        spec = app.openapi()
        missing = [
            f"{method} {path}"
            for method, path in PAGINATED_IN_FS_898
            if method.lower() not in spec.get("paths", {}).get(path, {})
        ]
        assert not missing, (
            f"these FS-898 routes no longer exist at the path this guard checks -- "
            f"update the register (renamed, moved, or removed):\n  "
            + "\n  ".join(sorted(missing))
        )

    def test_every_named_route_declares_limit_and_offset(self):
        offenders = [
            f"{method} {path}"
            for method, path in PAGINATED_IN_FS_898
            if not _has_limit_and_offset(path, method)
        ]
        assert not offenders, (
            "these routes were paginated in FS-898 and no longer declare both `limit` "
            "and `offset`:\n  " + "\n  ".join(sorted(offenders))
        )
