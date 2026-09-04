"""main.py's lifespan actually calls verify_rls_is_not_bypassed (FS-912).

`test_the_app_role_cannot_bypass_rls_realdb.py` proves the check function itself is
correct against a real database; nothing in this suite invokes `app.main.lifespan` end
to end (the `app` fixture other tests use overrides `get_db`/`get_tenant_db` for HTTP
tests without running FastAPI's lifespan context manager at all -- confirmed by grepping
this tree for any use of `LifespanManager` or a direct `lifespan(app)` call: there is
none). So the only thing standing between "the check exists" and "the check runs at boot"
is this file, checked statically rather than left to a very expensive real-uvicorn test.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _lifespan_source() -> ast.AST:
    tree = ast.parse((APP / "main.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            return node
    raise AssertionError("lifespan moved or was renamed; this guard is blind")


def test_lifespan_calls_the_rls_bypass_check():
    body = ast.unparse(_lifespan_source())
    assert "verify_rls_is_not_bypassed(" in body, (
        "lifespan() no longer calls verify_rls_is_not_bypassed -- the app would boot "
        "without ever confirming its own database role cannot see past row-level "
        "security"
    )


def test_the_check_runs_after_init_db_not_before():
    """A check that runs before init_db has no engine to check anything with, and one
    that silently gets skipped is worse than one that never existed -- named explicitly
    rather than trusted to source order."""
    body = ast.unparse(_lifespan_source())
    assert body.index("init_db()") < body.index("verify_rls_is_not_bypassed("), (
        "verify_rls_is_not_bypassed runs before init_db() in the unparsed lifespan body"
    )
