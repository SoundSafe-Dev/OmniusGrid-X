"""A session-scoped tenant GUC rides the pooled connection to the next request (FS-1017).

`set_config(name, value, is_local)` takes a third argument that decides how long the
setting lives. `true` scopes it to the current transaction; `false` scopes it to the
SESSION, which for a pooled connection means "until something else overwrites it".

Eleven call sites in this codebase pass `true`. One passed `false`:
`services/export_delivery.py`, in a worker that iterates every organisation in turn. So
after that worker ran, the connection it returned to the pool still carried the last
tenant's id.

WHY THAT IS WORSE THAN A MISSING GUC. SQLAlchemy's default `reset_on_return="rollback"`
issues a ROLLBACK when a connection goes back to the pool. A ROLLBACK clears
transaction-local settings and leaves session-level ones standing, so the leak survives
exactly the mechanism that looks like it would clean it up.

A later code path that reads an RLS-protected table without binding a tenant normally sees
**zero rows** — the policy matches nothing, which fails closed and is loud enough to find.
Inheriting a stale `app.current_org_id` turns that same path into a *successful read of
another tenant's rows*. The bug is upgraded from fail-closed to cross-tenant, and nothing
in the reading path looks wrong.

This is a text-level check on purpose: the argument is a literal at every call site, and
the property is "nobody writes `false` here" rather than anything about runtime behaviour.
"""
from __future__ import annotations

import re

import pytest

from tests._source_trees import PACKAGE_ROOTS, REPO_ROOT

#: `set_config('app.current_org_id', <anything>, <is_local>)` across one or more lines.
_SET_CONFIG = re.compile(
    r"set_config\(\s*'app\.current_org_id'\s*,\s*[^,]+,\s*(true|false)\s*\)",
    re.IGNORECASE,
)


def _without_comments(source: str) -> str:
    """Blank out `#` comments, preserving line numbering.

    THE FIRST VERSION OF THIS FILE FAILED ON ITS OWN FIX. The comment written above the
    corrected call site explains the defect by quoting it -- `set_config(..., false)` --
    and a plain text search cannot tell a description of the bug from the bug. That is
    the same trap this repository has hit before: a docstring satisfying an `in source`
    check. Comments are removed before matching so the guard reads code only.

    Deliberately naive about `#` inside string literals: the cost of blanking one is a
    missed detection in a line that also contains a comment character inside a SQL
    string, and every real call site here is a `text("SELECT set_config(...)")` with no
    `#` in it.
    """
    out = []
    for line in source.splitlines():
        stripped = line.split("#", 1)[0] if "#" in line else line
        out.append(stripped)
    return "\n".join(out)


def _tenant_guc_calls() -> list[tuple[str, int, str]]:
    """(path, line, is_local) for every tenant-GUC set in the shipped packages."""
    found = []
    for root in PACKAGE_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            text = _without_comments(path.read_text())
            for match in _SET_CONFIG.finditer(text):
                line = text[: match.start()].count("\n") + 1
                found.append((str(path.relative_to(REPO_ROOT)), line, match.group(1).lower()))
    return found


class TestTheDetectorSeesItsSubject:
    def test_it_finds_the_tenant_guc_call_sites(self):
        calls = _tenant_guc_calls()
        assert len(calls) >= 8, (
            f"only {len(calls)} `set_config('app.current_org_id', ...)` call sites found; "
            "the regex stopped matching rather than the codebase dropping tenant binding"
        )

    def test_it_would_detect_a_session_scoped_one(self):
        """Drive the matcher against a known-bad literal, so a green suite means the
        population is empty rather than the pattern being wrong."""
        sample = "text(\"SELECT set_config('app.current_org_id', :org, false)\")"
        match = _SET_CONFIG.search(sample)
        assert match and match.group(1) == "false"


class TestEveryTenantGucIsTransactionScoped:
    def test_none_is_session_scoped(self):
        offenders = [
            f"{path}:{line}" for path, line, is_local in _tenant_guc_calls()
            if is_local == "false"
        ]
        assert not offenders, (
            "tenant GUC set with is_local=false (session-scoped):\n  "
            + "\n  ".join(offenders)
            + "\n\nA session-scoped setting outlives its transaction and rides the pooled "
            "connection to whatever checks it out next -- SQLAlchemy's ROLLBACK on pool "
            "return clears transaction-local settings and leaves this one standing. A "
            "later reader that binds no tenant then inherits this one instead of seeing "
            "zero rows. Pass `true`."
        )
