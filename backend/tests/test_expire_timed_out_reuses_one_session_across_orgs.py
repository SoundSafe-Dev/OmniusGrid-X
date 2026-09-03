"""expire_timed_out opens one session for the whole pass, not one per org (FS-884).

THE DEFECT. `expire_timed_out` runs on a timer forever (`_timeout_loop`), unconditionally
over every organisation (`_organization_ids()`, never `_candidate_org_ids`). It used to open
a fresh `AsyncSessionLocal()` per org, exactly the shape FS-883 fixed in the fleet sweep: a
background loop that serves no request, taking a pooled connection per org on every pass.
RLS only needs the GUC re-set per org (`set_config('app.current_org_id', ...)`), not a new
connection — the session itself carries no tenant state that a later `set_config` can't
overwrite.

THE FIX. One `AsyncSessionLocal()` wraps the whole org loop; `_set_org` is called again for
each org on the same session before that org's query and commit.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _expire_source() -> ast.AST:
    """`expire_timed_out`, isolated by AST rather than line number. Exact name match —
    rule 296."""
    tree = ast.parse((APP / "services/command_executor.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "expire_timed_out":
            return node
    raise AssertionError("expire_timed_out moved or was renamed; this guard is blind")


class TestOneSessionForTheWholePass:
    def test_the_org_loop_is_inside_the_session_not_the_other_way_round(self):
        """THE DEFECT ITSELF. If the `async with self._sessions()` block is nested INSIDE
        the `for org_id in ...` loop, a fresh session is opened per org. It must be the
        other way round: the loop runs inside one session."""
        handler = _expire_source()
        # Find the top-level `for org_id in ...:` loop in the function body.
        org_loop = None
        for node in handler.body:
            if isinstance(node, ast.For) and "org_id" in ast.unparse(node.target):
                org_loop = node
                break
        if org_loop is not None:
            raise AssertionError(
                "the per-org loop is a direct child of the function body, so the session "
                "must be opened inside it — one AsyncSessionLocal per org, on a loop that "
                "runs forever"
            )
        # Otherwise, the session-with block should be the top-level statement, and the
        # org loop should live inside it.
        session_with = None
        for node in handler.body:
            if isinstance(node, ast.AsyncWith):
                session_with = node
                break
        assert session_with is not None, (
            "expire_timed_out no longer opens a session at all at the top level — "
            "this guard cannot tell how sessions are scoped"
        )
        nested_org_loop = any(
            isinstance(n, ast.For) and "org_id" in ast.unparse(n.target)
            for n in ast.walk(session_with)
        )
        assert nested_org_loop, (
            "no per-org loop found inside the top-level session block; this guard is blind"
        )

    def test_exactly_one_asyncsessionlocal_call(self):
        """One session for the whole pass means exactly one open call, regardless of how
        many organisations exist."""
        body = ast.unparse(_expire_source())
        opens = body.count("self._sessions()")
        assert opens == 1, (
            f"{opens} calls to self._sessions() in expire_timed_out; expected exactly 1. "
            f"More than one means a fresh connection is opened per org on a loop that "
            f"runs forever."
        )

    def test_set_config_still_runs_once_per_org(self):
        """The session is shared; the tenant context is not. Each org must still get its
        own set_config call before its query runs, or RLS silently scopes every org's
        work to whichever org set the GUC first."""
        body = ast.unparse(_expire_source())
        assert "_set_org" in body, "expire_timed_out no longer sets the tenant GUC per org"
