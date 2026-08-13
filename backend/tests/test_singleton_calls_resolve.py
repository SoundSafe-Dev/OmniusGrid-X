"""A call to a method that does not exist (FS-678).

`kanban.py` called `websocket_manager.broadcast_to_org(...)`. The method is
`broadcast_to_organization` and always has been. Python resolves attributes at call time, so
nothing said a word until the line ran — and the line runs inside a `BackgroundTasks` job,
*after* the 200 has gone out, so `route_walk` sees a healthy route and the live kanban board
simply never receives an event. It was found by the first real-database exercise of
`POST /kanban/tasks` in this suite, written for something else entirely (FS-677).

THE CHECK. Module-level singletons — `websocket_manager = WebSocketManager()` and its
hundred-odd siblings — are objects that exist at import time, so every attribute access on one
can be resolved against the real object with `hasattr`. 211 accesses across `app/`; all
resolve. The positive control is the literal line that shipped: put `broadcast_to_org` back and
this guard names it.

WHY PER-FILE IMPORTS AND NOT A GLOBAL NAME MAP. The first version built one `name -> object`
map for the whole tree and reported `main.py: twin_optimizer.router` as missing. `twin_optimizer`
there is the **module** `app.api.twin_optimizer`, which has a `router`; the singleton of the
same name is `app/services/twin_optimizer.py`, which does not. Name collision — the failure
this repository's detectors keep making — so each file is resolved through its own imports.

AND ONE THIS FILE ALMOST SHIPPED CLEAN. While mutation-testing, the detector was run as a
script file instead of through stdin. Python puts a script's own directory on `sys.path`, not
the working directory, so every `importlib.import_module("app...")` raised, every exception was
swallowed by the `except Exception` that exists for genuinely unimportable modules, `local`
stayed empty, and the sweep examined **nothing** — while printing exactly what a clean tree
prints. `test_the_sweep_examined_something` below is the assertion that makes that impossible:
a guard whose output is identical whether or not it ran is not a guard.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: Attributes reached on a singleton that exist only at runtime, with the reason. Empty
#: today; an entry here is a claim that the attribute is real and `hasattr` cannot see it.
DYNAMIC: dict[str, str] = {}


def _singletons_by_module() -> dict[str, set[str]]:
    """module path -> names bound to `Name = ClassName(...)` at module scope."""
    found: dict[str, set[str]] = {}
    for path in sorted(APP.rglob("*.py")):
        module = str(path.relative_to(APP.parent).with_suffix("")).replace("/", ".")
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                continue
            func = node.value.func
            if isinstance(func, ast.Name) and func.id[:1].isupper():
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found.setdefault(module, set()).add(target.id)
    return found


def _accesses():
    """(file, line, local_name, attribute, resolves) for each access on an imported singleton.

    Resolved through EACH FILE'S OWN IMPORTS. A global name map cannot tell
    `app.api.twin_optimizer` (a module, which has `.router`) from
    `app.services.twin_optimizer` (a singleton, which does not).
    """
    singletons = _singletons_by_module()
    for path in sorted(APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        local: dict[str, object] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.module):
                continue
            for alias in node.names:
                if alias.name not in singletons.get(node.module, set()):
                    continue
                try:
                    module = importlib.import_module(node.module)
                except Exception:
                    continue
                obj = getattr(module, alias.name, None)
                if obj is not None:
                    local[alias.asname or alias.name] = obj
        if not local:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in local
            ):
                yield (
                    str(path.relative_to(APP.parent)),
                    node.lineno,
                    node.value.id,
                    node.attr,
                    hasattr(local[node.value.id], node.attr),
                )


class TestTheSweepIsReal:
    def test_the_sweep_examined_something(self):
        """THE ASSERTION THAT MATTERS MOST IN THIS FILE.

        Every failure mode of this detector — a broken `sys.path`, a renamed package, an
        import that starts raising — empties the result and produces a report identical to a
        healthy tree. It happened once already, during this file's own mutation test.
        """
        count = len(list(_accesses()))
        assert count > 100, (
            f"only {count} singleton attribute accesses were resolved. Something stopped the "
            f"imports from working and this guard is now passing without looking at anything, "
            f"which is indistinguishable from a clean tree."
        )

    def test_singletons_are_found(self):
        modules = _singletons_by_module()
        assert sum(len(v) for v in modules.values()) > 50

    def test_a_module_is_not_mistaken_for_a_singleton_of_the_same_name(self):
        """`main.py` reaches `twin_optimizer.router`. That name is the API module there and a
        service singleton elsewhere, and the first draft reported it as a defect."""
        offenders = [
            a for a in _accesses() if a[2] == "twin_optimizer" and a[3] == "router" and not a[4]
        ]
        assert not offenders, (
            "a module is being resolved as the singleton that shares its name; the per-file "
            "import resolution has been replaced by a global name map"
        )

    def test_a_known_good_call_resolves(self):
        """Negative control against a real call rather than a constructed one."""
        good = [
            a
            for a in _accesses()
            if a[2] == "websocket_manager" and a[3] == "broadcast_to_organization"
        ]
        assert good and all(a[4] for a in good)


def test_every_singleton_attribute_exists():
    unresolved = sorted(
        f"{path}:{line} — {name}.{attr} does not exist on {name}"
        for path, line, name, attr, resolves in _accesses()
        if not resolves and f"{name}.{attr}" not in DYNAMIC
    )
    assert not unresolved, (
        f"{unresolved}\n\n"
        f"Python resolves attributes when the line runs, so this raises `AttributeError` at "
        f"the moment the feature is used and not before. If the call sits in a background "
        f"task — as `broadcast_to_org` did — the response has already been sent, the route "
        f"walk sees a 200, and the only symptom is a feature that quietly never happens."
    )


@pytest.mark.parametrize("entry", sorted(DYNAMIC))
def test_the_dynamic_exemptions_are_still_reached(entry):
    """An exemption for a call nobody makes hides a deletion rather than recording a
    decision. Vacuous while DYNAMIC is empty, which is the intended state."""
    name, attr = entry.split(".", 1)
    assert any(a[2] == name and a[3] == attr for a in _accesses()), (
        f"{entry} is exempted and no longer appears in the tree; delete the entry"
    )
