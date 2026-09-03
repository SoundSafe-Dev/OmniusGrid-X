"""compliance_reports.recover_stale_jobs opens one session per pass, not one per org (FS-885).

Same shape as FS-883 (edge_fleet_sweep) and FS-884 (command_executor.expire_timed_out):
a background recovery sweep that runs on a timer, unconditionally over every organisation,
used to open a fresh `AsyncSessionLocal()` per org. RLS only needs the tenant GUC re-set
per org, not a new pooled connection per org.
"""
from __future__ import annotations

import ast
import pathlib

WORKERS = pathlib.Path(__file__).resolve().parents[1] / "app" / "workers"


def _recover_source() -> ast.AST:
    """`recover_stale_jobs`, isolated by AST rather than line number. Exact name match —
    rule 296."""
    tree = ast.parse((WORKERS / "compliance_reports.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "recover_stale_jobs":
            return node
    raise AssertionError("recover_stale_jobs moved or was renamed; this guard is blind")


class TestOneSessionForTheWholePass:
    def test_the_org_loop_is_not_a_direct_child_of_the_function(self):
        """THE DEFECT ITSELF. A `for org_id in ...` loop as a direct statement of the
        function body (rather than nested inside a session block) means a fresh session
        is opened on every iteration."""
        handler = _recover_source()
        direct_org_loops = [
            node
            for node in handler.body
            if isinstance(node, ast.For) and "org_id" in ast.unparse(node.target)
        ]
        assert not direct_org_loops, (
            "the per-org loop is a direct child of the function body rather than nested "
            "inside a session block — one AsyncSessionLocal is being opened per org, on a "
            "loop that runs forever"
        )

    def test_at_most_two_asyncsessionlocal_calls(self):
        """One session to enumerate org ids (untenanted — Organization carries no RLS
        policy), one session reused for the whole per-org pass. More than two means a
        session is being opened inside the loop again."""
        body = ast.unparse(handler := _recover_source())
        opens = body.count("AsyncSessionLocal()")
        assert opens <= 2, (
            f"{opens} AsyncSessionLocal() opens in recover_stale_jobs; expected at most 2 "
            f"(one to list orgs, one reused for the per-org pass). More than one open "
            f"per org and this is back to a fresh connection per org on a loop that runs "
            f"forever."
        )

    def test_set_org_still_runs_once_per_org(self):
        body = ast.unparse(_recover_source())
        assert "_set_org" in body, "recover_stale_jobs no longer sets the tenant GUC per org"
