"""The ledger drains without being asked (FS-427).

`POST /shop-floor/postings/drain` was the only thing that moved a `pending` posting, and it
is a button on one page. An obligation raised by a part issue at 03:00 sat untouched until
somebody opened the Shop Floor screen. A queue nobody drains is exactly what the drainer was
written to remove, so leaving it manual moved the problem rather than fixing it: from
"nothing tries" to "nothing tries unless asked".

WHAT THESE ASSERT. Not that a loop exists — that the pass does the work, per organisation,
and that the two ways it can quietly do nothing are closed:

  * **One tenant's failure must not stop the rest.** An unreachable ERP for org A cannot
    leave org B's ledger untouched, and a scheduler that raises on the first bad tenant
    would do exactly that.
  * **It must not report a clean drain over rows it could not see.** `system_of_record_
    postings` has FORCE RLS, so a session without `app.current_org_id` reads zero rows and
    every summary comes back zeroed — absence arriving as a good result, which is the shape
    this repository keeps finding. The GUC is asserted to be set.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.posting_drain_scheduler import PostingDrainScheduler

pytestmark = pytest.mark.asyncio

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


class _Result:
    def __init__(self, **kw):
        self._summary = {"considered": 0, "posted": 0, "failed": 0,
                         "handed_to_a_person": 0, "orphaned": 0, **kw}

    def summary(self):
        return dict(self._summary)


class _Session:
    """Stands in for an AsyncSession: records the GUC it was given and the orgs listed."""

    def __init__(self, org_ids, log):
        self._org_ids = org_ids
        self._log = log

    async def execute(self, statement, params=None):
        text = str(statement)
        if "set_config" in text:
            self._log.append(("guc", params["org_id"]))
            return None
        self._log.append(("select_orgs", None))

        class _Rows:
            def __init__(self, ids): self._ids = ids
            def scalars(self): return self
            def all(self): return self._ids

        return _Rows(self._org_ids)

    async def commit(self):
        self._log.append(("commit", None))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _install(monkeypatch, org_ids, log, drain_impl):
    monkeypatch.setattr(
        "app.services.posting_drain_scheduler.AsyncSessionLocal",
        lambda: _Session(org_ids, log),
    )
    monkeypatch.setattr("app.services.posting_drain_scheduler.drain", drain_impl)


class TestThePassDoesTheWork:
    async def test_every_organisation_is_drained(self, monkeypatch):
        log, drained = [], []

        async def _drain(session, org_id, limit=50):
            drained.append(org_id)
            return _Result(considered=2, handed_to_a_person=2)

        _install(monkeypatch, [ORG_A, ORG_B], log, _drain)
        totals = await PostingDrainScheduler().drain_all_organizations()

        assert drained == [str(ORG_A), str(ORG_B)]
        assert totals["organizations"] == 2
        assert totals["considered"] == 4
        assert totals["handed_to_a_person"] == 4

    async def test_the_tenant_guc_is_set_before_every_drain(self, monkeypatch):
        """Without it, FORCE RLS hides every row and the pass reports a clean, empty drain.

        Absence arriving as a good result is the defect shape this codebase keeps finding;
        here it would look like a ledger that never has anything in it.
        """
        log = []

        async def _drain(session, org_id, limit=50):
            # The GUC for THIS org must already have been set when drain is called.
            assert ("guc", org_id) in log, f"drain ran for {org_id} with no GUC set"
            return _Result()

        _install(monkeypatch, [ORG_A, ORG_B], log, _drain)
        await PostingDrainScheduler().drain_all_organizations()

        assert [entry for entry in log if entry[0] == "guc"] == [
            ("guc", str(ORG_A)), ("guc", str(ORG_B)),
        ]

    async def test_the_work_is_committed(self, monkeypatch):
        """`drain` flushes; without a commit the statuses roll back and the next pass
        re-does the same work forever."""
        log = []

        async def _drain(session, org_id, limit=50):
            return _Result(considered=1, handed_to_a_person=1)

        _install(monkeypatch, [ORG_A], log, _drain)
        await PostingDrainScheduler().drain_all_organizations()

        assert ("commit", None) in log

    async def test_the_batch_size_is_passed_through(self, monkeypatch):
        """Bounded per organisation so one tenant's backlog cannot hold the loop."""
        seen = {}

        async def _drain(session, org_id, limit=50):
            seen["limit"] = limit
            return _Result()

        _install(monkeypatch, [ORG_A], [], _drain)
        await PostingDrainScheduler().drain_all_organizations()

        from app.core.config import settings

        assert seen["limit"] == settings.POSTING_DRAIN_BATCH_SIZE


class TestOneTenantCannotStopTheRest:
    async def test_a_failing_organisation_is_skipped_not_fatal(self, monkeypatch):
        drained = []

        async def _drain(session, org_id, limit=50):
            if org_id == str(ORG_A):
                raise RuntimeError("that tenant's ERP is unreachable")
            drained.append(org_id)
            return _Result(considered=3, posted=3)

        _install(monkeypatch, [ORG_A, ORG_B], [], _drain)
        totals = await PostingDrainScheduler().drain_all_organizations()

        assert drained == [str(ORG_B)], (
            "org B's ledger was not drained because org A failed first — one unreachable "
            "third party must not stop every other tenant"
        )
        assert totals["organizations"] == 1
        assert totals["posted"] == 3


class TestItIsGated:
    async def test_it_does_not_start_when_disabled(self, monkeypatch):
        """Same gate the other schedulers use. A background task that starts during a test
        run writes to whatever database the fixture happens to hold."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "POSTING_DRAIN_ENABLED", False)
        scheduler = PostingDrainScheduler()
        await scheduler.start()
        assert scheduler._task is None
        await scheduler.stop()
