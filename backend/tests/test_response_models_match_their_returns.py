"""Every key a handler returns must be named by the model that filters it.

THE SWEEP THIS AUTOMATES. Declaring `response_model` on 250 routes (pool #43) is
mechanical right up until it isn't: FastAPI **filters the response through the
model**, so a model that omits a key deletes it from the payload. 200, parses
fine, renders blank.

It has already happened twice in this burn-down, both caught by eye:

  * `query_performance`'s seven list endpoints each return `{<items>, "count"}`.
    The first version of their models declared only the items key, which would
    have removed `count` from all seven at once.
  * `exports`' three shapers were fine, but only because they were checked one at
    a time by hand.

Reading each handler and comparing by eye does not scale to the ~197 routes left,
and it is exactly the kind of check a machine does better. So this walks the AST
of every API module, finds handlers whose decorator sets `response_model=`, and
compares the model's field names to the keys of every **literal dict** the
handler returns.

HELPER-BUILT RETURNS ARE NOW COVERED TOO (FS-305). This originally read only the
handler's own literal dicts, so any file whose handlers return `_shaper(row)` or
`[_shaper(r) for r in rows]` was invisible — the keys are not in the handler's
syntax, so there was nothing to compare and the file passed by silence. That was
39 returns across 15 shapers in 7 modules, including `workcells`, `data_retention`
and `bulk_operations`, which this sweep had never examined at all; `fleet_logistics`
was the single file ever checked this way, by hand.

The envelope case is the one worth naming: a handler returning
`{"items": [_order_out(r) for r in rows], "total": n}` DID get checked — but only
its two envelope keys, stopping exactly at the boundary where the rows are shaped
and the interesting keys live.

WHAT IT STILL DELIBERATELY CANNOT SEE, and why that is acceptable:

  * a shaper that calls another shaper — one level only. Following further makes the
    key set depend on how the two compose, and a wrong answer is worse than none: it
    would name a field as dropped that is not.
  * handlers returning a bare variable or an ORM object — still not in the syntax.
    `exports` and `fleet_health` are covered for those by
    `test_declared_models_do_not_drop_fields`, which calls the shapers directly.
  * `**spread` inside a returned dict — the key set is not statically known, so that
    return is skipped rather than guessed at.

A partial check that states its own blind spots is worth more than a total one
that is wrong.

DIRECTION MATTERS. This asserts `returned_keys <= declared_fields` — every key
produced must be declared. The reverse (a field declared that nothing produces) is
`test_response_models_match_their_tables.py`, which answers it against the table
rather than the handler.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"

#: Routes whose returned keys legitimately exceed their model, with the reason.
#: Empty, and meant to stay that way — an entry here is a payload key the client
#: cannot see, so each one needs a reason a reader would accept.
ALLOWED_EXTRA: dict[str, str] = {}


def _decorator_response_model(node: ast.AST) -> str | None:
    """The `response_model=` argument of a @router.<method>(...) decorator, as source."""
    for dec in getattr(node, "decorator_list", []):
        if not isinstance(dec, ast.Call):
            continue
        func = dec.func
        if not (isinstance(func, ast.Attribute) and func.attr in
                {"get", "post", "put", "patch", "delete"}):
            continue
        for kw in dec.keywords:
            if kw.arg == "response_model":
                return ast.unparse(kw.value)
    return None


def _model_name(expr: str) -> str | None:
    """`List[Foo]` / `Dict[str, Foo]` / `Foo` -> `Foo`. None for anything else."""
    expr = expr.strip()
    if expr.startswith("List[") and expr.endswith("]"):
        expr = expr[5:-1].strip()
    elif expr.startswith("Dict[") and expr.endswith("]"):
        expr = expr[5:-1].split(",", 1)[-1].strip()
    return expr if expr.isidentifier() else None


def _literal_return_keysets(fn: ast.AST) -> list[set[str]]:
    """Key sets of every `return {...}` whose keys are all string literals.

    A dict containing `**spread` has an unknown key set and is skipped — better
    to check nothing than to check a guess.
    """
    out = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)):
            continue
        if any(k is None for k in node.value.keys):  # **spread
            continue
        if not all(isinstance(k, ast.Constant) and isinstance(k.value, str)
                   for k in node.value.keys):
            continue
        out.append({k.value for k in node.value.keys})
    return out


def _returned_helper_names(fn: ast.AST) -> set[str]:
    """Names of same-module shapers a handler returns the output of (FS-305).

    Covers the three shapes that actually occur here:

        return _zone_out(row)                      -> call
        return [_zone_out(r) for r in rows]        -> list comprehension over a call
        return {"items": [_order_out(r) for r ...  -> a shaper inside a returned dict

    The third matters more than it looks: those handlers DO return a literal dict, so
    the sweep above already checks the envelope's keys — and stops exactly at the
    boundary where the rows are shaped, which is where the interesting keys live.
    """
    names: set[str] = set()

    def _name_of(call: ast.Call) -> str | None:
        return getattr(call.func, "id", None)

    for node in ast.walk(fn):
        if not (isinstance(node, ast.Return) and node.value is not None):
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Call):
                name = _name_of(sub)
                if name and name.startswith("_") or (name and name.endswith("_out")):
                    names.add(name)
    return {n for n in names if n}


def _collect() -> list[tuple[str, str, str, set[str]]]:
    """(module, handler, model_name, returned_keys) for every checkable return.

    Two sources, and the second is FS-305: literal dicts returned by the handler, plus
    literal dicts returned by a same-module HELPER whose output the handler returns.

    Before this, any file whose handlers return `[_shaper(x) for x in rows]` was
    invisible to the sweep — the keys are not in the handler's syntax, so there was
    nothing to compare and the file passed by silence. That covered 39 returns across
    15 shapers in 7 modules, including `workcells`, `data_retention` and
    `bulk_operations`, which this sweep had never examined at all. `fleet_logistics`
    was the one file checked this way, by hand.

    ONE LEVEL, DELIBERATELY. A shaper that calls another shaper is not followed: the
    key set would then depend on how the two compose, and a wrong answer here is worse
    than no answer — it would name a field as dropped that is not.
    """
    found = []
    for path in sorted(API_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text())
        module_functions = {
            n.name: n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            declared = _decorator_response_model(node)
            if not declared:
                continue
            model = _model_name(declared)
            if model is None:
                continue
            for keys in _literal_return_keysets(node):
                found.append((path.stem, node.name, model, keys))
            for helper_name in _returned_helper_names(node):
                helper = module_functions.get(helper_name)
                if helper is None:
                    continue
                for keys in _literal_return_keysets(helper):
                    found.append((path.stem, f"{node.name}->{helper_name}", model, keys))
    return found


CASES = _collect()


def test_the_sweep_found_handlers_to_check():
    """Vacuity guard. If the AST shapes change — a new FastAPI decorator style, a
    rename — this file would silently check nothing and pass, which is the failure
    mode every sweep in this repo has a rule about."""
    assert len(CASES) > 40, (
        f"only {len(CASES)} declared handlers with literal-dict returns were found. "
        "The sweep is not seeing its subject; fix the AST matching rather than "
        "accepting the pass."
    )


def test_the_helper_following_still_works():
    """A SEPARATE floor for the FS-305 half, because the total above cannot protect it.

    Helper-derived cases are ~20% of the total. If the resolution broke — a rename, a
    changed shaper convention — the count would fall from 181 to roughly 145, sail past
    `> 40`, and seven modules would go back to passing by silence with nothing to say so.
    A sweep whose coverage can shrink invisibly is the failure mode this repo keeps
    finding, so the sub-population gets its own assertion.
    """
    helper_cases = [c for c in CASES if "->" in c[1]]
    assert len(helper_cases) >= 25, (
        f"only {len(helper_cases)} helper-built returns resolved (expected ~36 across "
        "workcells, data_retention, bulk_operations, exports, fleet_health, "
        "fleet_logistics). The shaper-name matching in `_returned_helper_names` has "
        "probably drifted — those modules are now unchecked, not clean."
    )


@pytest.mark.parametrize(
    "module,handler,model,keys",
    CASES,
    ids=[f"{m}.{h}" for m, h, _, _ in CASES],
)
def test_no_returned_key_is_dropped_by_its_model(module, handler, model, keys):
    mod = importlib.import_module(f"app.api.{module}")
    cls = getattr(mod, model, None)
    if cls is None or not hasattr(cls, "model_fields"):
        pytest.skip(f"{model} is not a local pydantic model (imported or aliased)")

    # AN OPEN MODEL CANNOT DROP A KEY, so this file's whole premise — "FastAPI will
    # DELETE those keys" — is not true of one. `extra="allow"` keeps every undeclared key
    # on the way out; `TestAnOpenModelReallyKeepsExtras` below proves that against a real
    # response rather than taking pydantic's word for it, because an exemption resting on
    # a framework behaviour nobody checked is how a real drop gets waved through.
    #
    # The correlation-evidence and operations-assistant routes are declared this way on
    # purpose: their payload keys are chosen by the engine per request, so a closed model
    # would delete tomorrow's keys silently. Being open is not being undocumented — the
    # coverage and permissive ratchets still require a real schema, and these have one.
    if cls.model_config.get("extra") == "allow":
        return

    declared = set(cls.model_fields)
    # A field may be populated under its alias on the wire.
    for name, field in cls.model_fields.items():
        if getattr(field, "alias", None):
            declared.add(field.alias)

    dropped = keys - declared
    dropped -= {k for k in dropped if f"{module}.{handler}.{k}" in ALLOWED_EXTRA}

    assert not dropped, (
        f"{module}.{handler} returns {sorted(dropped)}, which {model} does not "
        f"declare — FastAPI will DELETE those keys from the response. The client "
        f"sees 200 and a missing field.\n"
        f"  returned: {sorted(keys)}\n"
        f"  declared: {sorted(declared)}"
    )


class TestAnOpenModelReallyKeepsExtras:
    """The exemption above is a claim about FastAPI, so it is measured here.

    If a pydantic or FastAPI upgrade ever made `extra="allow"` stop passing undeclared keys
    through, every route exempted above would start dropping fields silently and this file
    would still be green. This test is what makes that impossible: it drives a real
    response and reads the body.
    """

    def test_an_undeclared_key_survives_the_response_model(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from pydantic import BaseModel, ConfigDict
        from typing import Optional

        class Open(BaseModel):
            model_config = ConfigDict(extra="allow")
            declared: Optional[str] = None

        probe = FastAPI()

        @probe.get("/probe", response_model=Open)
        def _probe():
            return {"declared": "yes", "undeclared": {"nested": [1, 2]}}

        body = TestClient(probe).get("/probe").json()
        assert body["undeclared"] == {"nested": [1, 2]}, (
            "`extra=\"allow\"` no longer preserves undeclared keys, so the exemption in "
            "test_no_returned_key_is_dropped_by_its_model is now hiding real field loss "
            "on every open model. Remove the exemption and declare the keys."
        )

    def test_a_closed_model_still_drops(self):
        """The other half. If this stopped dropping, the exemption would be pointless and
        the whole file would be asserting nothing."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from pydantic import BaseModel
        from typing import Optional

        class Closed(BaseModel):
            declared: Optional[str] = None

        probe = FastAPI()

        @probe.get("/probe", response_model=Closed)
        def _probe():
            return {"declared": "yes", "undeclared": "gone"}

        assert "undeclared" not in TestClient(probe).get("/probe").json()
