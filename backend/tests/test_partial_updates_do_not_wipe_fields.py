"""An update must not blank the fields it was not asked about (FS-403).

THE SHAPE. `model_dump()` on a partial-update model returns every field, including the ones
the caller never sent — as `None` if they are optional, or as the model's DEFAULT if they
have one. Applied to a row, that overwrites columns nobody mentioned.

It is silent data loss rather than an error, and it is invisible to the obvious test: send
`{"name": "New"}`, assert the name changed, pass. The fields it destroyed are the ones the
test did not look at. `test_writes_round_trip.py` asserts the other half — that a
name-only PUT leaves `vendor` alone — and this stops the pattern spreading to the handlers
that test does not reach.

THE DEFAULTED VARIANT IS THE DANGEROUS ONE. Blanking a column to NULL at least looks wrong
downstream. `HistorianRetentionSettings` gives every field a default, so a partial PUT
resets six retention settings to plausible-looking values — a cold-retention window quietly
returning from 3650 days to 1825 is not obviously a bug to anyone reading the row
afterwards.

MEASURED WHEN THIS WAS WRITTEN: 12 of 14 update handlers already exclude unset fields. This
is a convention the codebase follows and nothing enforced, which is the definition of one
that will eventually be broken. Both exceptions are recorded below with the reason each is
acceptable — an allowance, not an oversight.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

API = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"

#: A handler is an update if its name says so or it is mounted on PUT/PATCH.
_UPDATE_HINTS = ("update", "patch", "edit", "set_")

#: `file:function` allowed to call `model_dump()` without an exclusion, and why.
#: Each entry is a claim that has to stay true, not a convenience.
ALLOWED: dict[str, str] = {
    "kanban.py:update_task":
        "NOT the update payload — it dumps each nested `ChecklistItem` inside "
        "`[item.model_dump() for item in task_update.checklist_items]`, guarded by the "
        "field being present. Dumping a nested model in full is correct; the risk in this "
        "class is dumping the PATCH BODY in full.",
    "data_retention.py:update_historian_retention_policy":
        "a genuine full-replacement PUT: the route is PUT, `HistorianRetentionSettings` "
        "defaults every field, and the SQL sets every column. A partial body therefore "
        "means 'reset the rest to defaults', which is what PUT means. Recorded rather than "
        "changed because no client calls it today — but the first caller to treat it as a "
        "PATCH will silently reset six retention settings, so if a consumer appears, this "
        "entry should be revisited before it does.",
}


def _is_update(node) -> bool:
    if any(hint in node.name.lower() for hint in _UPDATE_HINTS):
        return True
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            func = dec.func
            if isinstance(func, ast.Attribute) and func.attr in ("put", "patch"):
                return True
    return False


def _unguarded_dumps() -> list[str]:
    """`file:function` for every update handler dumping a model with no exclusion."""
    found = []
    for path in sorted(API.glob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover - a syntax error fails loudly elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _is_update(node):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                func = sub.func
                if not (isinstance(func, ast.Attribute) and func.attr == "model_dump"):
                    continue
                if {k.arg for k in sub.keywords} & {"exclude_unset", "exclude_none"}:
                    continue
                found.append(f"{path.name}:{node.name}")
    return sorted(set(found))


class TestTheSweepCanSeeItsSubject:
    def test_it_finds_update_handlers(self):
        """A sweep that matches no handlers passes for the wrong reason."""
        handlers = []
        for path in API.glob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            handlers += [
                n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_update(n)
            ]
        assert len(handlers) >= 20, (
            f"only {len(handlers)} update handlers found; the name/decorator matching has "
            "drifted and this sweep is examining almost nothing"
        )

    def test_it_recognises_the_safe_form(self):
        """The detector must be able to see compliance, or every fixed handler would be
        re-reported and the guard would be abandoned as noise."""
        tree = ast.parse(
            "async def update_thing(payload):\n"
            "    values = payload.model_dump(exclude_unset=True)\n"
        )
        node = tree.body[0]
        assert _is_update(node)
        call = next(
            n for n in ast.walk(node)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "model_dump"
        )
        assert {k.arg for k in call.keywords} & {"exclude_unset", "exclude_none"}

    def test_it_would_catch_the_unsafe_form(self):
        tree = ast.parse(
            "async def update_thing(payload):\n"
            "    values = payload.model_dump()\n"
        )
        node = tree.body[0]
        call = next(
            n for n in ast.walk(node)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "model_dump"
        )
        assert not ({k.arg for k in call.keywords} & {"exclude_unset", "exclude_none"})


class TestNoUpdateWipesWhatItWasNotAsked:
    def test_every_unguarded_dump_is_allowed_with_a_reason(self):
        unexplained = [h for h in _unguarded_dumps() if h not in ALLOWED]
        assert not unexplained, (
            "these update handlers apply `model_dump()` without excluding unset fields, so "
            "a caller sending one field overwrites every other column with None or with the "
            "model's default. That is silent data loss, and the test that checks the field "
            "you DID send will pass.\n\nUse `model_dump(exclude_unset=True)`, or add an "
            "entry to ALLOWED explaining why full replacement is correct here:\n  "
            + "\n  ".join(unexplained)
        )

    def test_the_allowances_are_still_needed(self):
        """An allowance for a handler that has since been fixed is dead weight, and reads
        as permission for the next one."""
        stale = sorted(set(ALLOWED) - set(_unguarded_dumps()))
        assert not stale, (
            f"ALLOWED explains handlers that no longer need it: {stale}"
        )

    def test_the_convention_is_actually_followed(self):
        """The positive half. If everything were on the allowance list this would pass
        while asserting nothing about the codebase."""
        total = len(_unguarded_dumps())
        assert total <= 4, (
            f"{total} update handlers dump without exclusion. The convention was 12 of 14 "
            "compliant when this guard was written; a rise means it is being abandoned "
            "rather than followed."
        )
