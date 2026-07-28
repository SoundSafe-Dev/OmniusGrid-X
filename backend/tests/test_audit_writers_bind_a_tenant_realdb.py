"""Every audit write must bind a tenant, or the row is rejected and lost.

`audit_logs` is `ENABLE` + **FORCE** `ROW LEVEL SECURITY` (migrations 011/033). FORCE
means the policy applies to the table owner as well, so an INSERT is rejected outright
unless `app.current_org_id` is set on the connection. `AsyncSessionLocal` never sets it.

Four writers opened their own session, inserted, and caught the rejection in a broad
`except` that logged and moved on:

    app/services/audit.py       record_audit()   — the standalone (no caller session) path
    app/services/export_processor.py  _audit()
    app/services/bulk_processor.py    _audit()
    app/services/feature_flags.py     _audit()

So every export, every bulk job and every feature-flag change recorded nothing, while the
operation itself reported success. For a compliance surface that is the worst available
failure: the action happened, the evidence that it happened did not, and the only trace is
a log line nobody reads.

HOW IT WAS FOUND. Not by a sweep — in the LOG NOISE of an unrelated real-DB run.
`export_audit_failed ... new row violates row-level security policy for table
"audit_logs"` scrolled past three times while a different test was being written. The
same run also gave up `get_historical_oee`, which had never returned a row. Both had been
failing continuously and both were caught, logged and forgotten.

WHY WRITES AND NOT READS. Under RLS a read with no GUC silently returns zero rows; a
write is REJECTED loudly, then swallowed here. That asymmetry is the reason this class
persists: the loud error is caught two lines later, and what reaches a human is identical
to the quiet one.

`true`, not `false`, for `is_local`: these writers have no teardown that resets a
session-scoped setting, and the connection goes back to the pool carrying it.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Dict, List

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _audit_writers() -> List[tuple]:
    """(file, function, binds_a_tenant) for every function inserting into audit_logs."""
    found: List[tuple] = []
    for path in sorted(APP.glob("**/*.py")):
        source = path.read_text()
        if "audit_logs" not in source and "insert(AuditLog)" not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:  # another test's problem
            continue
        bodies: Dict[str, str] = {
            node.name: (ast.get_source_segment(source, node) or "")
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name, body in bodies.items():
            if "INSERT INTO audit_logs" not in body and "insert(AuditLog)" not in body:
                continue
            binds = "app.current_org_id" in body
            if not binds:
                # Follow one level of helper calls in the same module: report_scheduler
                # binds through `self._set_org`, and reading only the writer's own body
                # reported it as an offender when it was correct.
                for callee in set(re.findall(r"self\.(\w+)\s*\(", body)):
                    if callee in bodies and "app.current_org_id" in bodies[callee]:
                        binds = True
                        break
            found.append((str(path.relative_to(APP.parent)), name, binds))
    return found


WRITERS = _audit_writers()


class TestTheSweepIsNotVacuous:
    def test_it_finds_the_audit_writers(self):
        assert len(WRITERS) >= 6, (
            f"only {len(WRITERS)} audit writers found; the sweep is not reaching them "
            f"and would pass while checking nothing"
        )

    def test_the_canonical_writer_is_in_scope(self):
        assert any(name == "record_audit" for _f, name, _b in WRITERS), (
            "app/services/audit.py::record_audit is not being swept"
        )

    def test_the_helper_following_works(self):
        """`report_scheduler._audit_enqueue` binds via `self._set_org`. Reading only its
        own body called it an offender — a false positive of exactly the kind that
        teaches a reader to ignore this file."""
        binds = {
            (f, n): b for f, n, b in WRITERS if n == "_audit_enqueue"
        }
        assert binds and all(binds.values()), "helper-resolved binding regressed"


class TestEveryWriterBindsATenant:
    def test_no_audit_write_runs_without_tenant_context(self):
        offenders = [f"{f}::{n}()" for f, n, binds in WRITERS if not binds]
        assert not offenders, (
            "These INSERT into audit_logs, which is FORCE ROW LEVEL SECURITY, without "
            "setting app.current_org_id — so the row is REJECTED, and the broad `except` "
            "around it turns a rejection into a log line. The audited action succeeds "
            "and its evidence is lost:\n  " + "\n  ".join(offenders)
        )


@pytest_asyncio.fixture
async def audit_count(admin_sync_url):
    """Counts rows in audit_logs, bypassing RLS via the superuser connection."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True

    def count(org_id) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM audit_logs WHERE organization_id = %s", (str(org_id),)
            )
            return cur.fetchone()[0]

    yield count
    conn.close()


class TestTheRowActuallyLands:
    """The static check above proves a `set_config` call is present. Only a real
    database proves the policy accepts what follows it."""

    async def test_record_audit_writes_without_a_caller_session(
        self, app, seeded_orgs, audit_count
    ):
        from app.services.audit import record_audit

        org = seeded_orgs["org_a_id"]
        before = audit_count(org)
        wrote = await record_audit(
            session=None,
            action="test_standalone_audit",
            resource_type="test",
            organization_id=org,
            actor_id=seeded_orgs["user_a_id"],
            details={"origin": "test_audit_writers_bind_a_tenant_realdb"},
        )
        assert wrote is True, (
            "record_audit returned False — the INSERT was rejected, which is what it "
            "did on every standalone call before the GUC was bound"
        )
        assert audit_count(org) == before + 1, "no row landed despite a True result"

    async def test_the_row_carries_the_organisation_it_was_told(
        self, app, seeded_orgs, audit_count
    ):
        """A policy that accepted the row under the wrong org would satisfy the count
        above and break tenant isolation of the audit trail."""
        from app.services.audit import record_audit

        other_before = audit_count(seeded_orgs["org_b_id"])
        await record_audit(
            session=None,
            action="test_org_attribution",
            resource_type="test",
            organization_id=seeded_orgs["org_a_id"],
            actor_id=seeded_orgs["user_a_id"],
        )
        assert audit_count(seeded_orgs["org_b_id"]) == other_before

    async def test_an_export_audit_lands(self, app, seeded_orgs, audit_count):
        """The writer whose failure surfaced this. `export_audit_failed` fired three
        times in one smoke run and nothing downstream noticed."""
        from app.services.export_processor import export_processor

        org = seeded_orgs["org_a_id"]
        before = audit_count(org)
        await export_processor.audit_sync_export(
            "export_test_action", org, seeded_orgs["user_a_id"], total=3
        )
        assert audit_count(org) == before + 1, (
            "the export audit row was rejected again; RLS still refuses this INSERT"
        )


class TestTheEntryReachesTheAuditTrail:
    """Landing in the table is not the property that matters.

    The three assertions above count rows through a SUPERUSER connection, which bypasses
    RLS entirely — they prove the INSERT is no longer rejected. What an operator actually
    depends on is the entry being visible in `GET /api/v1/audit/logs`, read back through
    the tenant-scoped session as their own organisation. A row that lands but is filtered
    out on read is, from the compliance desk, the same as one that never landed.

    Written after noticing the original file proved only half of it.
    """

    async def test_a_standalone_audit_entry_is_listed(self, client_a, app, seeded_orgs):
        from app.services.audit import record_audit

        action = "test_visible_in_trail"
        assert await record_audit(
            session=None,
            action=action,
            resource_type="test",
            organization_id=seeded_orgs["org_a_id"],
            actor_id=seeded_orgs["user_a_id"],
        )

        response = await client_a.get("/api/v1/audit/logs", params={"limit": 200})
        assert response.status_code == 200, response.text
        body = response.json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        assert any(row.get("action") == action for row in items), (
            "the row was accepted by the database and does not appear in the audit "
            "trail — from the compliance desk that is indistinguishable from never "
            "having been written"
        )

    async def test_an_export_audit_is_listed(self, client_a, app, seeded_orgs):
        """The writer whose silent failure started this."""
        from app.services.export_processor import export_processor

        action = "test_export_visible_in_trail"
        await export_processor.audit_sync_export(
            action, seeded_orgs["org_a_id"], seeded_orgs["user_a_id"], total=2
        )
        body = (await client_a.get("/api/v1/audit/logs", params={"limit": 200})).json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        assert any(row.get("action") == action for row in items)

    async def test_another_organisation_does_not_see_it(
        self, client_a, client_b, app, seeded_orgs
    ):
        """Binding the GUC made these rows writable and readable. It must not have made
        them readable to everyone — the audit trail is the one table where a
        cross-tenant read is itself the incident."""
        from app.services.audit import record_audit

        action = "test_org_a_only"
        await record_audit(
            session=None,
            action=action,
            resource_type="test",
            organization_id=seeded_orgs["org_a_id"],
            actor_id=seeded_orgs["user_a_id"],
        )
        body = (await client_b.get("/api/v1/audit/logs", params={"limit": 200})).json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        assert not any(row.get("action") == action for row in items), (
            "org B can read org A's audit entries"
        )
