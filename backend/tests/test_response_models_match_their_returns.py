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

WHAT IT DELIBERATELY CANNOT SEE, and why that is acceptable:

  * handlers returning a variable, a helper call, or an ORM object — the keys are
    not in the syntax, so there is nothing to compare. `exports` and `fleet_health`
    are covered instead by `test_declared_models_do_not_drop_fields`, which calls
    the shaping helpers directly.
  * `**spread` inside a returned dict — the key set is not statically known, so
    that return is skipped rather than guessed at.

A partial check that states its own blind spots is worth more than a total one
that is wrong, and the two files together cover both shapes: literal returns here,
helper-built returns there.

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


def _collect() -> list[tuple[str, str, str, set[str]]]:
    """(module, handler, model_name, returned_keys) for every checkable return."""
    found = []
    for path in sorted(API_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text())
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
