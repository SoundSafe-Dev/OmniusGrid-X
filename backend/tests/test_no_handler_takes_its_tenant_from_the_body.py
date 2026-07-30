"""No route handler may read its organisation out of the request.

`POST /transportation/vehicles` did:

    organization_id=payload.get("organization_id")

so a caller could file a vehicle under any organisation they named, and a body that simply
omitted the field created a vehicle belonging to no tenant at all — invisible to its own
creator through any scoped read, and swept up by anything that scans the table unscoped.

This shape has been removed by hand at least six times in this repository: the yard trailer
list, the dock doors, the dock schedule, the maintenance schedule, the geofence zones and the
dashboard overview each carry a comment saying *"From the TOKEN, never the payload"*. Six
hand-fixes and no guard is the definition of a class that will come back — so this is the
guard.

WHAT IT CHECKS. Every function in `app/api` decorated as a route: no assignment or keyword
argument may take `organization_id` (or `organizationId`) from a name that is part of the
REQUEST. The tenant has exactly one legitimate source, `get_tenant_org_id`, which derives it
from the authenticated user.

WHY AST AND NOT GREP. `organization_id=payload.get("organization_id")` and
`organization_id=organization_id` differ only in the value expression, and a substring search
for the field name matches both — plus every comment explaining the defect, which in this
repository is a real problem (rule 37). Walking the tree lets the check look at what the value
actually IS.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"

ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete"}
TENANT_NAMES = {"organization_id", "organizationId", "org_id"}

#: Parameter names that carry client-controlled data. A tenant read out of any of these is
#: the defect; a tenant read from a `get_tenant_org_id` dependency is the fix.
REQUEST_SOURCES = {"payload", "body", "data", "settings_patch", "webhook_data", "event_data",
                   "feature_vector", "request", "req"}

#: Handlers allowed to read a tenant from the request, with the reason. Both are
#: unauthenticated vendor callbacks: there is no user to derive a tenant from, which is the
#: whole difficulty, and each resolves the tenant by verifying the payload's own secret.
ALLOWED: dict[str, str] = {
    "erp_webhooks.receive_erp_webhook": (
        "unauthenticated vendor callback. The tenant is whoever holds the secret that "
        "verifies the raw bytes, so the candidate lookup must span organisations by "
        "construction — see the comment in the handler."
    ),
    "geotab.geotab_webhook": (
        "unauthenticated vendor callback, same shape: no user context exists at the point "
        "the body arrives."
    ),
}


def _tenant_from_request(tree: ast.AST) -> list[tuple[str, int]]:
    """(function name, line) for each route handler that reads a tenant out of the request."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_route = any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and d.func.attr in ROUTE_DECORATORS
            for d in node.decorator_list
        )
        if not is_route:
            continue
        for inner in ast.walk(node):
            # `organization_id=<expr>` as a keyword argument, or `x.organization_id = <expr>`
            value = None
            if isinstance(inner, ast.keyword) and inner.arg in TENANT_NAMES:
                value = inner.value
            elif isinstance(inner, ast.Assign):
                for target in inner.targets:
                    name = getattr(target, "attr", None) or getattr(target, "id", None)
                    if name in TENANT_NAMES:
                        value = inner.value
            if value is None:
                continue
            # Does the value come from a request-carried name?
            for sub in ast.walk(value):
                base = None
                if isinstance(sub, ast.Name):
                    base = sub.id
                elif isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                    base = sub.value.id
                if base in REQUEST_SOURCES:
                    found.append((node.name, inner.lineno))
                    break
    return found


FILES = sorted(API.rglob("*.py"))
OFFENDERS: list[str] = []
for path in FILES:
    for func, line in _tenant_from_request(ast.parse(path.read_text())):
        key = f"{path.stem}.{func}"
        if key not in ALLOWED:
            OFFENDERS.append(f"{path.name}:{line} {func}()")


class TestTheSweepIsNotVacuous:
    def test_it_reaches_the_api_modules(self):
        # If the path or the decorator convention changes, this file passes while inspecting
        # nothing — the failure mode every guard in this repository has had at least once.
        assert len(FILES) > 30, f"only {len(FILES)} files under app/api"

    def test_it_finds_route_handlers(self):
        total = 0
        for path in FILES:
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                    isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Attribute)
                    and d.func.attr in ROUTE_DECORATORS
                    for d in node.decorator_list
                ):
                    total += 1
        assert total > 300, f"only {total} route handlers found"

    def test_it_flags_the_shape_it_exists_for(self):
        """The positive control, on the defect as it was actually written."""
        source = """
@router.post("/vehicles")
async def create_vehicle(payload: dict, db=Depends(get_tenant_db)):
    vehicle = Vehicle(organization_id=payload.get("organization_id"))
"""
        assert _tenant_from_request(ast.parse(source)) == [("create_vehicle", 4)]

    def test_it_accepts_a_tenant_from_the_dependency(self):
        """The fix must not be reported. A guard that flags both is a guard nobody can act
        on — and `organization_id=organization_id` differs from the defect only in the value
        expression, which is exactly why this walks the tree instead of grepping."""
        source = """
@router.post("/vehicles")
async def create_vehicle(payload: dict, organization_id=Depends(get_tenant_org_id)):
    vehicle = Vehicle(organization_id=organization_id)
"""
        assert _tenant_from_request(ast.parse(source)) == []

    def test_it_ignores_a_function_that_is_not_a_route(self):
        """A service helper may legitimately be handed a tenant by its caller; the rule is
        about the trust boundary, which is the route."""
        source = """
async def run_sync(payload: dict):
    row = Thing(organization_id=payload.get("organization_id"))
"""
        assert _tenant_from_request(ast.parse(source)) == []


class TestNoHandlerTakesItsTenantFromTheBody:
    def test_there_are_no_offenders(self):
        assert not OFFENDERS, (
            "these route handlers read their organisation out of the request, which lets a "
            "caller choose the tenant they write to:\n  " + "\n  ".join(OFFENDERS) +
            "\n\nUse `organization_id: UUID = Depends(get_tenant_org_id)`. If the handler is "
            "an unauthenticated vendor callback with genuinely no user context, add it to "
            "ALLOWED with the reason."
        )


class TestTheExemptionsStayHonest:
    @pytest.mark.parametrize("key", sorted(ALLOWED))
    def test_the_exempted_handler_still_exists(self, key):
        """An exemption for a handler that has been renamed or deleted silently widens the
        allowlist."""
        module, func = key.split(".", 1)
        path = API / f"{module}.py"
        assert path.exists(), f"{key} names a module that is gone"
        names = {
            node.name
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert func in names, f"{key} names a handler that no longer exists"

    def test_every_exemption_says_why(self):
        for key, reason in ALLOWED.items():
            assert len(reason) > 50, f"{key}'s reason is too thin to audit"
