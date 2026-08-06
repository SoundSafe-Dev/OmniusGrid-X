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
downstream. `HistorianRetentionSettings` gave every field a default, so a partial PUT
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
    "data_retention.py:update_historian_retention_policy":
        "a genuine full-replacement PUT, and now a safe one (FS-470). The route is PUT, "
        "the SQL sets every column, and PUT means replace — so dumping the whole body is "
        "correct. What made it a trap was `HistorianRetentionSettings` defaulting every "
        "field, so a partial body silently reset six retention settings instead of "
        "failing. The handler now takes `HistorianRetentionReplace`, which requires all "
        "seven, so a partial body is a 422 naming the missing field. The defaults stay on "
        "the base model, which CREATE inherits — sane values are what a default is for, "
        "and replacing an existing policy is not.",
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
            # THE PATCH BODY, not any model in reach (FS-470). The receiver must be one
            # of the handler's own parameters — the object FastAPI parsed the request into.
            #
            # `kanban.update_task` does `[item.model_dump() for item in
            # task_update.checklist_items]`: dumping a nested model in full is correct, and
            # the risk in this class is dumping the PATCH BODY in full. That distinction
            # was carried as an allowance for months; it is a property of the code and can
            # simply be read.
            parameters = {
                a.arg for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs
            }
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                func = sub.func
                if not (isinstance(func, ast.Attribute) and func.attr == "model_dump"):
                    continue
                if not (isinstance(func.value, ast.Name) and func.value.id in parameters):
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


class TestTheReplacementPUTRefusesAPartialBody:
    """The allowance above says a partial body is now a 422 rather than a silent reset.
    That is a claim about a model, so it is checked (FS-470)."""

    def test_every_field_is_required(self):
        from app.api.data_retention import HistorianRetentionReplace

        optional = [
            name
            for name, field in HistorianRetentionReplace.model_fields.items()
            if not field.is_required()
        ]
        assert not optional, (
            f"{optional} are optional on the PUT body, so omitting them resets those "
            f"columns to defaults instead of failing. That is the trap the allowance "
            f"describes as closed."
        )

    def test_a_partial_body_is_rejected(self):
        """The behaviour, not just the model. A validator or a default reintroduced
        elsewhere would pass the field check above."""
        import pytest as _pytest
        from pydantic import ValidationError

        from app.api.data_retention import HistorianRetentionReplace

        with _pytest.raises(ValidationError) as exc:
            HistorianRetentionReplace(hot_retention_days=30)
        assert "cold_retention_days" in str(exc.value)

    def test_a_complete_body_is_still_accepted(self):
        """The other direction: a model that rejects everything passes both tests above
        and breaks the endpoint."""
        from app.api.data_retention import HistorianRetentionReplace

        policy = HistorianRetentionReplace(
            hot_retention_days=30,
            warm_retention_days=365,
            cold_retention_days=1825,
            ingestion_priority=3,
            ingestion_sample_rate=1.0,
            max_ingest_age_seconds=30,
            archival_enabled=True,
        )
        assert policy.cold_retention_days == 1825

    def test_create_still_has_its_defaults(self):
        """`HistorianRetentionCreate` inherits the defaulting base on purpose. Making the
        base required would have closed this entry by breaking policy creation."""
        from app.api.data_retention import HistorianRetentionCreate

        created = HistorianRetentionCreate()
        assert created.hot_retention_days == 30
        assert created.metric_name == "*"

    def test_the_handler_uses_the_replacement_model(self):
        import inspect

        from app.api.data_retention import update_historian_retention_policy

        signature = inspect.signature(update_historian_retention_policy)
        assert signature.parameters["policy"].annotation.__name__ == (
            "HistorianRetentionReplace"
        ), "the PUT handler is back on the defaulting model, so a partial body resets"

