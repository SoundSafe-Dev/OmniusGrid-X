"""Workers must bind the tenant transaction-locally, and every session must bind one.

WHY WORKERS NEED THEIR OWN GUARD. `get_tenant_db` resolves a tenant from an
authenticated user; a worker has no request and no user, so it sets
`app.current_org_id` by hand from the message or job it is processing. Nothing in the API
guards check that, and a worker that gets it wrong fails in the two ways this codebase has
seen repeatedly: reads return nothing, and writes to a FORCE-RLS table are rejected
outright.

TWO RULES, both learned the hard way elsewhere in this repo.

1. **Transaction-local (`true`), never session-scoped (`false`).** A session-scoped value
   stays on the connection after the session closes and it returns to the pool, so the
   next task to pick that connection up inherits a stale tenant unless it sets its own.
   `export_delivery` used `false` in two places. Every operation there does set its own,
   so nothing was leaking today — but that is a property of the current code, not of the
   mechanism, and it is the same footgun `get_tenant_db` had to be fixed for.

2. **Every session that touches tenant data binds one.** The compliance worker has 14
   `AsyncSessionLocal()` blocks and 13 `_set_org` calls. The one without is NOT a defect —
   it hands the session to `build_report_payload`, which calls `set_tenant_guc` itself —
   and that exception is asserted here rather than left as a discrepancy someone has to
   re-derive.

The ingestion worker is the model: one `set_config(..., true)` per message, one commit at
the end, so the binding covers the whole transaction. Pinned below, because a second
commit mid-message would silently drop the GUC for everything after it.
"""

from __future__ import annotations

import pathlib
import re

import pytest

WORKERS = pathlib.Path(__file__).resolve().parents[1] / "app" / "workers"

SESSION_SCOPED = re.compile(r"set_config\(\s*'app\.current_org_id'[^)]*,\s*false\s*\)", re.I)
TRANSACTION_LOCAL = re.compile(r"set_config\(\s*'app\.current_org_id'[^)]*,\s*true\s*\)", re.I)


def _worker_sources():
    return {p.name: p.read_text() for p in sorted(WORKERS.glob("*.py")) if p.name != "__init__.py"}


class TestTheSweepIsNotVacuous:
    def test_workers_are_found(self):
        assert len(_worker_sources()) >= 4, "worker discovery is broken"

    def test_at_least_one_worker_binds_a_tenant(self):
        """If none did, the rules below would pass while checking nothing."""
        assert any(
            TRANSACTION_LOCAL.search(src) for src in _worker_sources().values()
        ), "no worker sets app.current_org_id; this guard is asserting nothing"


class TestTheBindingIsTransactionLocal:
    @pytest.mark.parametrize("name", sorted(_worker_sources()))
    def test_no_session_scoped_tenant_guc(self, name):
        source = _worker_sources()[name]
        hits = SESSION_SCOPED.findall(source)
        assert not hits, (
            f"app/workers/{name} sets app.current_org_id with is_local=false. That value "
            f"survives the session and rides the connection back into the pool, so the "
            f"next task inherits a stale tenant unless it happens to set its own. Use "
            f"true — the binding then covers exactly the transaction that needs it."
        )


class TestEverySessionBindsATenant:
    """The compliance worker is the one with a documented exception."""

    def test_compliance_sessions_bind_or_delegate(self):
        source = (WORKERS / "compliance_reports.py").read_text()
        lines = source.splitlines()
        unbound = []
        for i, line in enumerate(lines):
            if "async with AsyncSessionLocal() as session" not in line:
                continue
            window = "\n".join(lines[i : i + 8])
            if "_set_org(session" in window:
                continue
            # The documented exception: handed to a callee that binds it itself.
            if "generate_and_store_report(" in window:
                continue
            unbound.append(i + 1)
        assert not unbound, (
            f"app/workers/compliance_reports.py opens a session at line(s) {unbound} "
            f"without binding a tenant and without delegating to something that does. "
            f"Reads will return nothing and writes to a FORCE-RLS table will be rejected."
        )

    def test_the_documented_exception_still_delegates(self):
        """If `build_report_payload` stops setting the GUC, the exception above becomes
        a hole. Pinned so the two cannot drift apart."""
        service = (
            WORKERS.parents[0] / "services" / "compliance_report_service.py"
        ).read_text()
        assert "set_tenant_guc(session" in service, (
            "build_report_payload no longer binds the tenant itself, so the compliance "
            "worker's one unbound session is now a real gap"
        )


class TestIngestionBindsOncePerMessage:
    def test_the_message_path_commits_exactly_once(self):
        """A transaction-local GUC is dropped by a commit. The ingestion worker binds
        once per message and commits once at the end; a second commit inside the same
        message would silently unbind everything after it."""
        source = (WORKERS / "ingestion.py").read_text()
        start = source.index("async def _process_message")
        end = source.index("async def ", start + 10)
        body = source[start:end]

        # Count only the TENANT-BOUND branch: from the set_config to the end. The
        # agent-status branch above it returns first and is a separate session, so a
        # whole-function commit count says 2 and means nothing. That over-crude version
        # of this assertion is what led to the missing binding in the heartbeat handler
        # being found, so it earned its keep before being corrected.
        assert body.count("set_config") == 1, "the per-message binding is no longer unique"
        bound = body[body.index("set_config"):]
        assert bound.count("await session.commit()") == 1, (
            "the tenant-bound branch of _process_message now commits more than once; "
            "a transaction-local GUC is dropped by a commit, so everything after the "
            "first one runs unbound"
        )
