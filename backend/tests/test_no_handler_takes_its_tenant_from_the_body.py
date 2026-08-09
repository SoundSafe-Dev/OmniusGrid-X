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
import re

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


#: Handlers that take a tenant as a PARAMETER and validate it against the token. A path
#: parameter naming a resource is legitimate — `GET /organizations/{organization_id}` has to
#: accept one — provided the handler refuses when it is not the caller's.
VALIDATED_PATH_PARAM: dict[str, str] = {
    "workcells.get_organization": (
        "path parameter on GET /organizations/{organization_id}, compared against "
        "get_tenant_org_id and 404'd when it differs — the resource id IS the tenant here, so "
        "accepting it is unavoidable and checking it is the whole job."
    ),
}


def _client_supplied_tenant_params(tree: ast.AST, module: str) -> list[tuple[str, int]]:
    """Route handlers taking `organization_id`/`org_id` as a client-supplied parameter.

    THE SECOND VARIANT OF THE SAME CLASS, and the AST check above misses it: these handlers do
    not ASSIGN the tenant from a request, they RECEIVE it as a query parameter and use it in a
    where clause. Eight were found this way — six in geotab.py, plus get_active_operations and
    get_detention_alerts — and every one was Optional, so a request that simply omitted the
    parameter filtered by nothing at all.

    Whether that leaked depended entirely on whether the table carried a policy, which is the
    same coin-flip that decided the fourteen body-tenant handlers.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and d.func.attr in ROUTE_DECORATORS
            for d in node.decorator_list
        ):
            continue
        if f"{module}.{node.name}" in VALIDATED_PATH_PARAM:
            continue
        args = node.args
        params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        defaults = list(args.defaults) + list(args.kw_defaults or [])
        # right-align defaults with parameters
        padded = [None] * (len(params) - len(defaults)) + defaults
        for param, default in zip(params, padded):
            if param.arg not in TENANT_NAMES:
                continue
            rendered = ast.unparse(default) if default is not None else ""
            if "Depends" in rendered:
                continue
            found.append((node.name, node.lineno))
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


PARAM_OFFENDERS: list[str] = []
for path in FILES:
    for func, line in _client_supplied_tenant_params(ast.parse(path.read_text()), path.stem):
        PARAM_OFFENDERS.append(f"{path.name}:{line} {func}()")


class TestNoHandlerTakesItsTenantFromAParameter:
    def test_there_are_no_offenders(self):
        assert not PARAM_OFFENDERS, (
            "these route handlers accept the organisation as a client-supplied parameter "
            "rather than deriving it from the token:\n  " + "\n  ".join(PARAM_OFFENDERS) +
            "\n\nUse `Depends(get_tenant_org_id)`. If it is a PATH parameter naming the "
            "resource, validate it against the token and add the handler to "
            "VALIDATED_PATH_PARAM with the reason."
        )

    def test_it_flags_an_optional_query_parameter(self):
        """The shape as found, and Optional is the dangerous part: a request omitting the
        parameter filtered by nothing at all."""
        source = """
@router.get("/devices")
async def get_geotab_devices(organization_id: Optional[UUID] = None, db=Depends(get_db)):
    return await service.get_devices(organization_id=organization_id, db=db)
"""
        assert _client_supplied_tenant_params(ast.parse(source), "geotab") == [
            ("get_geotab_devices", 3)
        ]

    def test_it_accepts_the_dependency_form(self):
        source = """
@router.get("/devices")
async def get_geotab_devices(organization_id: UUID = Depends(get_tenant_org_id)):
    return []
"""
        assert _client_supplied_tenant_params(ast.parse(source), "geotab") == []

    def test_it_accepts_a_validated_path_parameter(self):
        """`GET /organizations/{organization_id}` must accept one; it compares against the
        token and 404s. Listing it is not a loophole — the entry says what makes it safe, and
        `test_the_allowed_path_params_still_validate` checks the comparison is still there."""
        source = """
@router.get("/{organization_id}")
async def get_organization(organization_id: UUID, org_id=Depends(get_tenant_org_id)):
    if str(organization_id) != str(org_id):
        raise HTTPException(status_code=404, detail="organization not found")
"""
        assert _client_supplied_tenant_params(ast.parse(source), "workcells") == []

    def test_the_allowed_path_params_still_validate(self):
        """An allowlist entry claims the handler CHECKS the parameter. If someone removes the
        comparison, the entry silently becomes a hole — so the comparison is asserted, with
        comments stripped (rule 37)."""
        for key in VALIDATED_PATH_PARAM:
            module, func = key.split(".", 1)
            source = (API / f"{module}.py").read_text()
            source = re.sub(r"#[^\n]*", "", source)
            start = source.index(f"async def {func}(")
            body = source[start : start + 900]
            assert "get_tenant_org_id" in body, f"{key} no longer derives a tenant to compare"
            assert "!=" in body and "404" in body, (
                f"{key} is allowlisted as a VALIDATED path parameter but no longer compares "
                "it against the token"
            )


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
