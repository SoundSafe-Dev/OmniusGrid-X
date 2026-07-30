"""Every query against the four fleet tables must carry its own organisation filter.

`fleet_logistics._scope` is the application half of migration 051's order — application filter
first, policy second. Both halves are load-bearing for different reasons:

  * the POLICY is what holds on Postgres when a handler forgets its predicate;
  * the FILTER is what holds on the SQLite offline path, where row-level security does not
    exist at all, and it is what makes a missing predicate a visible bug rather than a
    silently empty page.

`vehicle_service_history` had neither. It took no `org_id` dependency — the only handler in the
file that did not — and filtered `repair_orders` on `vehicle_id` and status alone, returning
description, cost, vendor and the technician's notes for whatever vehicle id it was given. The
policy covered it on Postgres; on SQLite it was a cross-tenant read. Its sibling one function
above, on the same table and the same shape, was scoped.

WHY AN AST CHECK AND NOT A CONVENTION. Twenty-two of the twenty-three call sites already did
the right thing, which is exactly the state in which the twenty-third is invisible: nothing
about it looks unusual, and the reviewer's eye is calibrated by the other twenty-two. The
question — *is this `select()` wrapped in `_scope`?* — has a definite answer that a parser can
give, so rule 38 says ask that one rather than a broader one about tenancy in general.
"""

from __future__ import annotations

import ast
import pathlib

MODULE = pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "fleet_logistics.py"

#: The tables migration 051 covers, and the ones `_scope` is written for. All four carry
#: `organization_id` as VARCHAR(36) rather than a UUID column, which is the other reason the
#: helper exists — see its docstring.
TENANT_MODELS = {"GeofenceZone", "GeofenceAlert", "MaintenanceSchedule", "RepairOrder"}

#: `select(X)` calls that legitimately carry no `_scope`, with why. Empty, and that is the
#: point: every one of the twenty-three is scoped. An entry here is a claim that a particular
#: query cannot leak, and it has to say how.
UNSCOPED_BY_DESIGN: dict[str, str] = {}


def _select_model(call: ast.Call) -> str | None:
    """The model name in `select(Model)` / `select(Model.col)`, if it is one."""
    if not (isinstance(call.func, ast.Name) and call.func.id == "select" and call.args):
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Name):
        return arg.id
    if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
        return arg.value.id
    return None


def _scoped_select_lines(tree: ast.AST) -> set[int]:
    """Line numbers of `select(...)` calls that sit inside a `_scope(...)` call."""
    scoped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_scope":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and _select_model(sub):
                    scoped.add(sub.lineno)
    return scoped


def _findings() -> tuple[list[str], int]:
    """`(unscoped call sites, total tenant selects)`."""
    source = MODULE.read_text()
    tree = ast.parse(source)
    lines = source.splitlines()
    scoped = _scoped_select_lines(tree)

    unscoped: list[str] = []
    total = 0
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            model = _select_model(node)
            if model not in TENANT_MODELS:
                continue
            total += 1
            if node.lineno in scoped:
                continue
            key = f"{func.name}:{model}"
            if key in UNSCOPED_BY_DESIGN:
                continue
            unscoped.append(f"{key} (line {node.lineno}): {lines[node.lineno - 1].strip()[:80]}")
    return unscoped, total


class TestTheScanIsNotVacuous:
    def test_it_finds_the_tenant_queries(self):
        """If `select` stops being matched — a rename, an import alias — every assertion below
        passes over an empty set."""
        _, total = _findings()
        assert total >= 15, f"only {total} queries against the four fleet tables found"

    def test_it_can_tell_scoped_from_unscoped(self):
        """The positive control, in the exact shape the defect had: a `select()` on one of the
        four models with a `where` and no `_scope` around it."""
        sample = ast.parse(
            "async def h(db):\n"
            "    await db.execute(\n"
            "        select(RepairOrder).where(RepairOrder.vehicle_id == v)\n"
            "    )\n"
        )
        scoped = _scoped_select_lines(sample)
        calls = [
            n for n in ast.walk(sample)
            if isinstance(n, ast.Call) and _select_model(n) == "RepairOrder"
        ]
        assert calls, "the sample's select() was not recognised"
        assert calls[0].lineno not in scoped

    def test_it_recognises_the_wrapped_form(self):
        """The negative control. `_scope(select(X).where(...), X, org)` must NOT be reported,
        or the guard flags all twenty-three and gets switched off."""
        sample = ast.parse(
            "async def h(db, org_id):\n"
            "    await db.execute(\n"
            "        _scope(select(RepairOrder).where(RepairOrder.id == i), RepairOrder, org_id)\n"
            "    )\n"
        )
        scoped = _scoped_select_lines(sample)
        calls = [
            n for n in ast.walk(sample)
            if isinstance(n, ast.Call) and _select_model(n) == "RepairOrder"
        ]
        assert calls[0].lineno in scoped


class TestNoFleetQueryEscapesItsOrganisation:
    def test_every_select_is_scoped(self):
        """THE ASSERTION THIS FILE EXISTS FOR. Twenty-two of twenty-three call sites already
        did this, which is precisely the state in which the twenty-third is invisible."""
        unscoped, _ = _findings()
        assert not unscoped, (
            "these queries against the four fleet tables carry no organisation filter:\n  "
            + "\n  ".join(unscoped)
            + "\n\nOn Postgres migration 051's policy covers a miss; on the SQLite offline "
            "path there is no policy, so the filter is the only thing there. Wrap it in "
            "`_scope(query, Model, org_id)`, or add an entry to UNSCOPED_BY_DESIGN saying how "
            "the query cannot leak."
        )

    def test_every_handler_that_queries_them_takes_an_org(self):
        """The related smell, and the one that made the defect visible: the handler had no
        `org_id` parameter at all. A scoped query needs one, so its absence is a reliable
        tell — and easier to see in review than a missing wrapper deep in a call."""
        source = MODULE.read_text()
        tree = ast.parse(source)
        missing: list[str] = []
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            touches = any(
                _select_model(n) in TENANT_MODELS
                for n in ast.walk(func)
                if isinstance(n, ast.Call)
            )
            if not touches:
                continue
            args = func.args
            names = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
            if "org_id" not in names:
                missing.append(func.name)
        assert not missing, (
            f"these handlers query a tenant table without taking an org_id: {missing}"
        )
