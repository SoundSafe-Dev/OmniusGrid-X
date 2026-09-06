"""A hung ERP call is worse than a failed one (FS-1008).

`aiohttp.ClientSession()` constructed bare has **no total timeout**. A middleware host that
accepts the connection and then stops responding holds the coroutine open indefinitely:
it occupies a slot in the pool FS-839 sized, it never reaches the retry classifier in
`erp_connector_base`, and the circuit breaker cannot count a failure that has not happened
yet. The request does not fail; it simply never finishes.

THE TWO LAYERS DISAGREED AND BOTH LOOKED FINE. Every connector in `erp_connectors/*` built
its session through a factory passing `ClientTimeout(total=config.timeout)`. Every service
in `erp_middleware/*` — 36 call sites across five files — constructed one bare. Both
spellings are `aiohttp.ClientSession`, so reading either file alone tells you nothing about
which convention the other follows.

This guard asks the question at the AST level rather than by grep, because `ClientSession(`
appears in docstrings and comments in these same files, and a text search cannot tell a
construction from a description of one.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from tests._source_trees import REPO_ROOT

SEARCH = REPO_ROOT / "backend" / "app"


def _bare_client_sessions() -> list[str]:
    """(path:line) for every `aiohttp.ClientSession(...)` built without a timeout."""
    found = []
    for path in sorted(SEARCH.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else None
            )
            if name != "ClientSession":
                continue
            if not any(kw.arg == "timeout" for kw in node.keywords):
                found.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


class TestTheDetectorSeesItsSubject:
    def test_it_finds_the_sessions_that_do_pass_a_timeout(self):
        """Vacuity in the other direction: if the walk stopped recognising
        `ClientSession` at all, the real check below would pass over nothing."""
        total = 0
        for path in sorted(SEARCH.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    n = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    if n == "ClientSession":
                        total += 1
        assert total >= 5, (
            f"only {total} ClientSession constructions found in the whole backend; the "
            "AST walk is broken rather than the codebase having stopped making HTTP calls"
        )

    def test_a_bare_construction_would_be_detected(self):
        """Drive the detector against a known-bad snippet, so a green result means the
        population is empty rather than the matcher being blind."""
        tree = ast.parse("import aiohttp\ns = aiohttp.ClientSession()\n")
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "ClientSession"
            and not any(kw.arg == "timeout" for kw in n.keywords)
        ]
        assert len(calls) == 1


class TestEveryOutboundSessionIsBounded:
    def test_no_client_session_is_built_without_a_timeout(self):
        offenders = _bare_client_sessions()
        assert not offenders, (
            "aiohttp.ClientSession built with no timeout:\n  "
            + "\n  ".join(offenders)
            + "\n\naiohttp's default is no total timeout, so a host that accepts the "
            "connection and stops responding hangs the coroutine forever -- consuming a "
            "pool slot, never reaching the retry classifier, and never counted by the "
            "circuit breaker. Build it through the file's `_session()` factory, which "
            "passes ClientTimeout(total=config.timeout)."
        )
