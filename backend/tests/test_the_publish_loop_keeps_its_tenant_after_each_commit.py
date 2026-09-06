"""A transaction-local GUC dies at the first commit, and this loop commits per job (FS-1017).

`export_delivery._publish_queued_for_org` marks each job published and commits **inside the
loop**, deliberately: "a crash re-publishes at most one job". That design interacts with
tenant binding in a way that is easy to get wrong in either direction, and this codebase
has now been on both sides of it:

  * The original code bound the tenant with `set_config(..., is_local=false)` — SESSION
    scope. That survives the per-job commits, so the loop worked. It also outlived the
    worker: SQLAlchemy's `reset_on_return="rollback"` clears transaction-local settings and
    leaves session-level ones standing, so the tenant id rode the pooled connection to
    whoever checked it out next. A later reader that binds no tenant would then inherit it
    and read another tenant's rows instead of seeing zero.

  * Flipping it to `is_local=true` fixes the leak and **silently breaks the loop**: the
    first `commit()` ends the transaction the binding belonged to, so every later
    iteration issues its UPDATE unbound. Under FORCE ROW LEVEL SECURITY that matches
    nothing — zero rows updated, no error, jobs left queued while the worker reports
    success.

The fix is neither: transaction scope, re-bound after each commit. This file pins the half
that a passing suite would otherwise miss, because the failure mode of getting it wrong is
silence rather than an exception.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from tests._source_trees import REPO_ROOT

SOURCE = REPO_ROOT / "backend" / "app" / "services" / "export_delivery.py"


def _publish_loop_body() -> ast.AST:
    tree = ast.parse(SOURCE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_publish_queued_for_org":
            return node
    raise AssertionError("_publish_queued_for_org not found — was it renamed?")


class TestTheBindingIsTransactionScoped:
    def test_set_org_passes_is_local_true(self):
        """The leak half. `false` would put the tenant id on the pooled connection."""
        text = SOURCE.read_text()
        assert "set_config('app.current_org_id', :org, true)" in text
        # And not the session-scoped form anywhere in executable code — the dedicated
        # guard `test_the_tenant_guc_is_transaction_scoped.py` covers the whole tree; this
        # is the local assertion so a reader of this file sees both halves together.


class TestTheLoopRebindsAfterEveryCommit:
    def test_a_set_org_call_follows_the_in_loop_commit(self):
        """The correctness half.

        Asserted structurally rather than by running a real database, because the failure
        is *zero rows updated with no error* — a behavioural test needs live Postgres with
        RLS forced to see anything at all, and the structural property ("the loop re-binds
        after committing") is the thing a future edit would break.
        """
        func = _publish_loop_body()
        loops = [n for n in ast.walk(func) if isinstance(n, ast.For)]
        assert loops, "the per-job loop is gone — this file's premise no longer holds"

        rebound = False
        for loop in loops:
            statements = list(ast.walk(loop))
            committed_at = None
            for i, node in enumerate(statements):
                if isinstance(node, ast.Attribute) and node.attr == "commit":
                    committed_at = i
                if (
                    committed_at is not None
                    and isinstance(node, ast.Attribute)
                    and node.attr == "_set_org"
                ):
                    rebound = True
        assert rebound, (
            "`_publish_queued_for_org` commits inside its loop but never re-binds the "
            "tenant afterwards. The GUC is transaction-local, so every iteration after "
            "the first runs unbound: under FORCE ROW LEVEL SECURITY the UPDATE matches "
            "nothing, zero rows change, and the worker reports success having published "
            "nothing."
        )

    def test_the_queue_loop_does_not_need_one(self):
        """The inverse, so this file is not asserting a blanket rule it does not mean.
        `_queue_due_for_org` commits once, after its loop, so its binding is still live
        for every statement that depends on it."""
        tree = ast.parse(SOURCE.read_text())
        func = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_queue_due_for_org"
        )
        loops = [n for n in ast.walk(func) if isinstance(n, ast.For)]
        commits_in_loop = [
            n for loop in loops for n in ast.walk(loop)
            if isinstance(n, ast.Attribute) and n.attr == "commit"
        ]
        assert not commits_in_loop, (
            "`_queue_due_for_org` now commits inside its loop too, so it needs the same "
            "re-bind as the publish loop — and this test needs updating to say so."
        )
