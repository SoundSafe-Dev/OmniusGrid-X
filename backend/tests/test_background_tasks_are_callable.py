"""A background task whose arguments do not fit its function (FS-679).

`background_tasks.add_task(fn, a, b, c)` is checked when the task runs, and it runs **after the
response has been sent**. So a wrong argument count is a 200 to the caller, an exception into
Starlette's background runner, and a feature that quietly never happens — the same blind spot
that hid `broadcast_to_org` (FS-678), reached by getting the *name* right and the *call* wrong.

`route_walk` cannot see it. It drives every route looking for 5xx, and by the time the task
fails the status code has already been decided (rule 139, from the other side).

THE CHECK. Resolve each `add_task` target — a module-level function, an imported one, or a
method on a singleton — and `inspect.signature(...).bind(...)` the arguments the call site
supplies. Fifteen sites in `app/`, all fifteen resolved, all binding cleanly. Mutation-verified
by adding one positional argument to the kanban broadcast, which the check names.

WHY THE RESOLUTION IS THREE-WAY, and why that mattered. The first version resolved only names
imported from other `app` modules, and reported **ten of fifteen targets as unresolvable** —
including all seven kanban broadcasts, which are defined in the file that schedules them. Ten
unresolved out of fifteen is not a finding, it is a detector examining a third of its subject;
`test_every_target_resolves` below makes that state fail rather than pass quietly.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _resolvable_names(path: pathlib.Path, tree: ast.AST) -> dict[str, object]:
    """Callables reachable from this file: its own definitions, then its `app` imports.

    Own definitions FIRST and imports second, because a name imported into a module does not
    shadow one defined there — and the seven kanban broadcasts are same-module.
    """
    local: dict[str, object] = {}
    own = str(path.relative_to(APP.parent).with_suffix("")).replace("/", ".")
    try:
        for name, obj in vars(importlib.import_module(own)).items():
            if callable(obj):
                local.setdefault(name, obj)
    except Exception:
        pass
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app")):
            continue
        try:
            module = importlib.import_module(node.module)
        except Exception:
            continue
        for alias in node.names:
            obj = getattr(module, alias.name, None)
            if obj is not None:
                local[alias.asname or alias.name] = obj
    return local


def _sites():
    """(file, line, label, target, positional_count, keyword_names) per `add_task` call."""
    for path in sorted(APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        source = path.read_text()
        if "add_task" not in source:
            continue
        local = _resolvable_names(path, tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_task"
                and node.args
            ):
                continue
            target_node = node.args[0]
            target = None
            if isinstance(target_node, ast.Name):
                target = local.get(target_node.id)
            elif isinstance(target_node, ast.Attribute) and isinstance(target_node.value, ast.Name):
                base = local.get(target_node.value.id)
                if base is not None:
                    target = getattr(base, target_node.attr, None)
            yield (
                str(path.relative_to(APP.parent)),
                node.lineno,
                ast.unparse(target_node),
                target,
                len(node.args) - 1,
                [kw.arg for kw in node.keywords if kw.arg],
            )


class TestTheSweepIsReal:
    def test_sites_are_found(self):
        """Vacuity, in the form rule 165 exists for: an empty result and a clean result are
        the same string."""
        assert len(list(_sites())) >= 10, (
            "fewer than ten add_task sites found; the AST walk has stopped descending"
        )

    def test_every_target_resolves(self):
        """The first draft resolved five of fifteen and reported the other ten as
        'unresolvable', which reads like a warning and behaves like a blind spot."""
        unresolved = [f"{s[0]}:{s[1]} {s[2]}" for s in _sites() if s[3] is None]
        assert not unresolved, (
            f"{unresolved}\n\nThese background targets could not be resolved, so their "
            f"arguments were never checked. Extend the resolution rather than accepting a "
            f"partial sweep — an unchecked site is indistinguishable from a correct one."
        )

    def test_a_known_good_site_binds(self):
        """Negative control against a real call: the kanban broadcast takes exactly three."""
        good = [s for s in _sites() if s[2] == "broadcast_task_update"]
        assert good, "the kanban broadcasts have moved; this control is stale"
        for site in good:
            inspect.signature(site[3]).bind(*[object()] * site[4])


def test_every_background_task_can_be_called_with_the_arguments_given():
    mismatched = []
    for path, line, label, target, positional, keywords in _sites():
        if target is None:
            continue
        try:
            inspect.signature(target).bind(
                *[object()] * positional, **{name: object() for name in keywords}
            )
        except TypeError as error:
            mismatched.append(f"{path}:{line} — add_task({label}, ...): {error}")
    assert not mismatched, (
        f"{mismatched}\n\n"
        f"The arguments are checked when the task runs, and it runs after the response has "
        f"been sent. A mismatch is a 200 to the caller, a traceback in a background runner, "
        f"and a feature that silently never happens."
    )
