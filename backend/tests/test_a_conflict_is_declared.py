"""A route that can answer 409 must declare it, and one that cannot must not (FS-728).

`common_responses` documents 400/401/403/404/405/422/429/500 on every route, because those
arise from the shared machinery. It deliberately EXCLUDES 409, and says why:

    NOT added here, deliberately: 409 and 503. […] a handler raises 409 only where a
    conflict is possible […] Declaring them on all ~450 operations would document responses
    most of them cannot produce, and an OpenAPI document that over-promises misleads the
    generated SDK exactly as much as one that under-promises.

That reasoning is right and nothing enforced the other half of it. **45 routes raise 409 and
none declared it** — a duplicate user, a second open labour entry, a rollout already running,
an asset already down, a schedule whose name is taken. The contract gate saw nine of them
answer an undocumented 409 (only nine because generated input has to actually collide), and a
client generated from the schema had no branch for the one status that means *your request was
well-formed and the world was not*.

WHY THIS IS A CHECK AND NOT A LIST. Membership is derivable from the code: a route can answer
409 if its own body raises it, or if a helper in the same module does. Both directions are
asserted, because each fails differently —

  * a route that CAN conflict and does not declare it leaves the SDK without a branch;
  * a route that declares it and CANNOT leaves the SDK with a branch that never runs, and is
    the "over-promise" the module comment warns about.

THE HELPER HOP IS DELIBERATELY ONE LEVEL. `shop_floor.start_downtime` raises directly;
`users.create_user` raises through `_reject_duplicate_email`. Following further would need a
call graph, and every instance in the tree today is within one hop — which is worth stating
rather than leaving as an accident: if a raise ever moves two hops away this check goes quiet,
so the vacuity test below pins the population size.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from app.main import app
from tests._route_tree import http_routes

API_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"

RAISES_409 = ("HTTP_409_CONFLICT", "status_code=409")


def _can_conflict(source: str, tree: ast.AST, node: ast.AST) -> bool:
    """Does this handler raise 409 — itself, or through a same-module helper it calls?"""
    local = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    body = ast.get_source_segment(source, node) or ""
    if any(marker in body for marker in RAISES_409):
        return True
    for name in set(re.findall(r"\b(\w+)\s*\(", body)) & set(local):
        helper = ast.get_source_segment(source, local[name]) or ""
        if any(marker in helper for marker in RAISES_409):
            return True
    return False


def _handlers() -> dict[str, bool]:
    """endpoint function name -> whether it can answer 409."""
    out: dict[str, bool] = {}
    for path in sorted(API_DIR.glob("*.py")):
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover - unparseable modules fail elsewhere
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in {"get", "post", "put", "patch", "delete"}
                for d in node.decorator_list
            ):
                continue
            out[f"{path.stem}.{node.name}"] = _can_conflict(source, tree, node)
    return out


def _declared() -> dict[str, bool]:
    """endpoint function name -> whether its OpenAPI operation declares 409."""
    schema = app.openapi()
    out: dict[str, bool] = {}
    for route, full, methods in http_routes(app):
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None or full not in schema["paths"]:
            continue
        for method in {m.lower() for m in methods} & set(schema["paths"][full]):
            key = f"{endpoint.__module__.rsplit('.', 1)[-1]}.{endpoint.__name__}"
            declares = "409" in (schema["paths"][full][method].get("responses") or {})
            out[key] = out.get(key, False) or declares
    return out


class TestTheMeasurementIsReal:
    def test_it_finds_both_kinds(self):
        """Vacuity in both directions. If the AST walk broke, every route would look
        conflict-free and this file would pass over nothing."""
        handlers = _handlers()
        assert len(handlers) > 300, f"only {len(handlers)} route handlers parsed"
        can = [k for k, v in handlers.items() if v]
        assert len(can) > 30, f"only {len(can)} handlers found that raise 409"
        assert len(can) < len(handlers) / 2, "almost everything looks like a conflict"

    def test_a_known_conflicting_route_is_detected(self):
        """`start_downtime` refuses a second open downtime event for one asset. If this
        stops being detected, the helper-hop or the marker list has drifted."""
        assert _handlers().get("shop_floor.start_downtime") is True

    def test_a_known_non_conflicting_route_is_not(self):
        """The other control. Listing assets cannot conflict with anything."""
        assert _handlers().get("assets.list_assets") is False


class TestEveryConflictIsDeclared:
    def test_no_route_can_conflict_without_saying_so(self):
        handlers, declared = _handlers(), _declared()
        missing = sorted(
            name
            for name, can in handlers.items()
            if can and name in declared and not declared[name]
        )
        assert not missing, (
            f"{missing} can answer 409 and do not declare it. A generated client has no "
            f"branch for the one status that means the request was fine and the world was "
            f"not. Add `responses={{**conflict_response}}` to the route."
        )

    def test_no_route_declares_a_conflict_it_cannot_produce(self):
        """The over-promise direction, which `app/core/responses.py` argues is equally bad:
        an SDK branch that never runs is a claim the API does not keep."""
        handlers, declared = _handlers(), _declared()
        phantom = sorted(
            name
            for name, declares in declared.items()
            if declares and name in handlers and not handlers[name]
        )
        assert not phantom, (
            f"{phantom} declare 409 and nothing in them raises it. Either the raise was "
            f"removed and the declaration outlived it, or it was never true."
        )
