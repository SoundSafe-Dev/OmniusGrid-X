"""A background loop that fails every iteration reported `ok` (FS-693).

CARRIED ACROSS FROM FS-691, which found the same shape in the edge agent: a collector
polling a device that answered 500 forever had a perfectly healthy task, so a gauge derived
from `task.done()` read *up* while the asset produced nothing. The question that finding
leaves behind is *where else is health computed from the mechanism rather than the work?* —
and the answer in the backend is the command dispatch loop, which is worse, because commands
are how an operator reaches a machine.

`_dispatch_loop` catches every exception per iteration and continues. That is right: one
poisoned command must not stop dispatch for the whole fleet. It also means the task never
exits, so `_dispatch_task.done()` — the entire old health check — is False forever. A
misconfigured producer, an unreadable row, a schema drift: `command_dispatch: ok`, and not
one command dispatched. The operator's health page is green while their command sits pending.

WHAT IS ASSERTED HERE is the distinction, not the implementation: a loop that is failing
every iteration must be reported as failing, and a loop that is merely *running* must not
be. The second half matters as much as the first — a check that reported every busy loop as
broken would be turned off within a week.
"""

from __future__ import annotations

import asyncio

import pytest

from app.api import health as health_module

pytestmark = pytest.mark.asyncio


class _Executor:
    """Stands in for `command_executor` with its loop state set by hand.

    A REAL TASK, not a mock, for `_dispatch_task`: the check calls `.done()` on it, and a
    Mock answers every attribute truthily — which would make the exited-loop branch fire on
    a healthy executor and quietly invert the test.
    """

    def __init__(self, *, running=True, failures=None, task=None):
        self._running = running
        self._loop_failures = failures if failures is not None else {"dispatch": 0, "timeout": 0}
        self._dispatch_task = task


def _with(monkeypatch, executor):
    import app.services.command_executor as ce

    monkeypatch.setattr(ce, "command_executor", executor)


class TestAFailingLoopIsReported:
    async def test_a_dispatch_loop_failing_every_iteration_is_an_error(self, monkeypatch):
        """THE PROPERTY. Before this, the same state answered `ok`."""
        _with(monkeypatch, _Executor(failures={"dispatch": 9, "timeout": 0}))
        status, details = health_module._check_command_dispatch()

        assert status.startswith("error"), (
            "a dispatch loop that has failed nine times in a row is not healthy; the task "
            "being alive says nothing, because the loop is written never to die"
        )
        assert "dispatch" in status
        assert details["consecutive_failures"]["dispatch"] == 9

    async def test_the_timeout_loop_is_covered_too(self, monkeypatch):
        """Nothing examined `_timeout_loop` at all. Commands that should expire silently
        never do, and every instrument said the subsystem was fine."""
        _with(monkeypatch, _Executor(failures={"dispatch": 0, "timeout": 5}))
        status, _ = health_module._check_command_dispatch()
        assert status.startswith("error") and "timeout" in status

    async def test_the_failing_loop_is_named(self, monkeypatch):
        """An error saying only 'a loop is failing' sends the operator to read logs for
        three subsystems. Both loops failing must name both."""
        _with(monkeypatch, _Executor(failures={"dispatch": 4, "timeout": 4}))
        status, _ = health_module._check_command_dispatch()
        assert "dispatch" in status and "timeout" in status


class TestAWorkingLoopIsNotReported:
    """NEGATIVE CONTROLS. A check that fired on a healthy system would be disabled, and the
    silent-dispatch case would be invisible again — this time behind an ignored alert."""

    async def test_a_running_loop_with_no_failures_is_ok(self, monkeypatch):
        _with(monkeypatch, _Executor())
        status, details = health_module._check_command_dispatch()
        assert status == "ok"
        assert details["running"] is True

    async def test_a_transient_failure_does_not_trip_it(self, monkeypatch):
        """One bad iteration is a hiccup, not an outage. The counter resets on the next
        success, so a threshold of one would page on ordinary DB contention."""
        _with(monkeypatch, _Executor(failures={"dispatch": 1, "timeout": 0}))
        status, _ = health_module._check_command_dispatch()
        assert status == "ok"

    async def test_a_stopped_executor_still_says_not_running(self, monkeypatch):
        """The pre-existing states are unchanged; this finding added a case, it did not
        replace the ones that worked."""
        _with(monkeypatch, _Executor(running=False))
        status, _ = health_module._check_command_dispatch()
        assert status == "not_running"

    async def test_an_exited_loop_is_still_an_error(self, monkeypatch):
        """The old check tested something real — just not the only real thing."""
        loop = asyncio.get_running_loop()
        finished = loop.create_future()
        finished.set_result(None)
        _with(monkeypatch, _Executor(task=finished))
        status, _ = health_module._check_command_dispatch()
        assert status.startswith("error") and "exited" in status


class TestTheExportSchedulerToo:
    """The first entry taken off the unwatched register, by writing the check rather than
    deleting the line. `ExportScheduler._run` has the same swallow-and-continue shape, so a
    scheduler whose every cycle throws leaves scheduled exports undelivered indefinitely and
    the customer finds out before the operator does."""

    async def test_a_scheduler_failing_every_iteration_is_an_error(self, monkeypatch):
        from app.services import export_delivery

        monkeypatch.setattr(export_delivery.export_scheduler, "_running", True)
        monkeypatch.setattr(export_delivery.export_scheduler, "_consecutive_failures", 6)
        status, details = health_module._check_export_scheduler()
        assert status.startswith("error")
        assert details["consecutive_failures"] == 6

    async def test_a_working_scheduler_is_ok(self, monkeypatch):
        from app.services import export_delivery

        monkeypatch.setattr(export_delivery.export_scheduler, "_running", True)
        monkeypatch.setattr(export_delivery.export_scheduler, "_consecutive_failures", 0)
        assert health_module._check_export_scheduler()[0] == "ok"

    async def test_disabled_is_reported_as_its_own_state(self, monkeypatch):
        """DISABLED IS NOT BROKEN, and it is not healthy either. `start()` returns
        immediately when the flag is off, so `_running` stays False and a check that only
        knew ok/not_running would report a deployment posture as a fault — or, worse,
        an operator would read `export_scheduler: ok` on an instance where exports were
        never turned on."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "EXPORT_SCHEDULER_ENABLED", False)
        status, details = health_module._check_export_scheduler()
        assert status == "disabled"
        assert details["enabled"] is False

    async def test_a_stopped_scheduler_is_distinguished_from_a_failing_one(self, monkeypatch):
        from app.services import export_delivery

        monkeypatch.setattr(export_delivery.export_scheduler, "_running", False)
        monkeypatch.setattr(export_delivery.export_scheduler, "_consecutive_failures", 0)
        assert health_module._check_export_scheduler()[0] == "not_running"

    async def test_the_scheduler_loop_maintains_its_counter(self):
        """Drives the real `_run`, because the check is only as good as the state it reads
        and that state is written in another file."""
        from app.services.export_delivery import ExportScheduler

        scheduler = ExportScheduler()
        scheduler._running = True
        calls = {"n": 0}

        async def _boom():
            calls["n"] += 1
            if calls["n"] >= 2:
                scheduler._running = False
            raise RuntimeError("redpanda is unreachable")

        scheduler.dispatch_due = _boom
        with pytest.MonkeyPatch.context() as mp:
            from app.core.config import settings

            mp.setattr(settings, "EXPORT_SCHEDULER_INTERVAL_SECONDS", 0.01)
            await scheduler._run()

        assert scheduler._consecutive_failures >= 2

    async def test_the_export_check_reaches_the_detailed_report(self, monkeypatch):
        """A check nothing calls is the FS-691 shape one level up. This asserts the wiring,
        which is a separate fact from the check being correct."""
        checks, details = await health_module._run_extended_checks(_Boom())
        assert "export_scheduler" in checks
        assert "export_scheduler" in details


class _Boom:
    """A session whose every use raises — the extended checks must survive one."""

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("connection refused")


class TestTheReportSchedulerToo:
    """APScheduler catches a job's exception and keeps the schedule, so `dispatch_due`
    failing every scan enqueues no compliance report forever — and a missed compliance
    report is discovered by an auditor. The `_scan` wrapper exists because APScheduler
    gives the job no other way to say it ran and achieved nothing."""

    async def test_a_scan_failing_every_cycle_is_an_error(self, monkeypatch):
        from app.services import report_scheduler as rs

        monkeypatch.setattr(rs.report_scheduler, "_started", True)
        monkeypatch.setattr(rs.report_scheduler, "_consecutive_scan_failures", 4)
        status, _ = health_module._check_report_scheduler()
        assert status.startswith("error")

    async def test_a_working_scan_is_ok(self, monkeypatch):
        from app.services import report_scheduler as rs

        monkeypatch.setattr(rs.report_scheduler, "_started", True)
        monkeypatch.setattr(rs.report_scheduler, "_consecutive_scan_failures", 0)
        assert health_module._check_report_scheduler()[0] == "ok"

    async def test_disabled_is_its_own_state(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "COMPLIANCE_REPORT_SCHEDULER_ENABLED", False)
        assert health_module._check_report_scheduler()[0] == "disabled"

    async def test_the_wrapper_counts_and_still_raises(self):
        """The counter must not change what APScheduler sees — its own logging of the
        traceback is the existing signal, and `_scan` swallowing would erase it."""
        from app.services.report_scheduler import ComplianceReportScheduler

        scheduler = ComplianceReportScheduler()

        async def _boom(now=None):
            raise RuntimeError("relation does not exist")

        scheduler.dispatch_due = _boom
        with pytest.raises(RuntimeError):
            await scheduler._scan()
        assert scheduler._consecutive_scan_failures == 1

    async def test_the_wrapper_resets_on_success(self):
        from app.services.report_scheduler import ComplianceReportScheduler

        scheduler = ComplianceReportScheduler()
        scheduler._consecutive_scan_failures = 5

        async def _fine(now=None):
            return None

        scheduler.dispatch_due = _fine
        await scheduler._scan()
        assert scheduler._consecutive_scan_failures == 0

    async def test_the_scheduled_job_is_the_wrapper_not_the_bare_method(self):
        """The counter lives in `_scan`; if `start()` registers `dispatch_due` directly the
        counting silently stops while every other test here still passes. Source-level
        because starting APScheduler in a unit test is the kind of double rule 191 warns
        about."""
        import inspect

        from app.services import report_scheduler as rs

        source = inspect.getsource(rs.ComplianceReportScheduler.start)
        assert "self._scan" in source, (
            "start() no longer schedules the counting wrapper — a dispatch_due that "
            "throws every scan is invisible to health again"
        )


class TestTheErrorTrackerToo:
    """If the flush loop breaks, errors stop being persisted — and a system that has
    stopped reporting errors looks exactly like a system that has stopped having them.
    Every subsystem that fails loudly depends on this one working quietly."""

    async def test_flushes_failing_every_cycle_is_an_error(self, monkeypatch):
        from app.services import error_tracker as et

        monkeypatch.setattr(et.error_tracker, "enabled", True)
        monkeypatch.setattr(et.error_tracker, "_task", object())
        monkeypatch.setattr(et.error_tracker, "_consecutive_flush_failures", 3)
        status, _ = health_module._check_error_tracker()
        assert status.startswith("error")
        assert "not being recorded" in status

    async def test_a_working_tracker_is_ok(self, monkeypatch):
        from app.services import error_tracker as et

        monkeypatch.setattr(et.error_tracker, "enabled", True)
        monkeypatch.setattr(et.error_tracker, "_task", object())
        monkeypatch.setattr(et.error_tracker, "_consecutive_flush_failures", 0)
        assert health_module._check_error_tracker()[0] == "ok"

    async def test_disabled_is_its_own_state(self, monkeypatch):
        from app.services import error_tracker as et

        monkeypatch.setattr(et.error_tracker, "enabled", False)
        assert health_module._check_error_tracker()[0] == "disabled"

    async def test_the_flush_loop_maintains_its_counter(self, monkeypatch):
        """Drives the real `_run` with a flush that always raises."""
        from app.services.error_tracker import ErrorTracker
        from app.services import error_tracker as et

        monkeypatch.setattr(et, "FLUSH_INTERVAL_SECONDS", 0.01)
        tracker = ErrorTracker()
        calls = {"n": 0}

        async def _boom():
            calls["n"] += 1
            if calls["n"] >= 2:
                tracker._stopping = True
            raise RuntimeError("db gone")

        tracker._flush_once = _boom
        await tracker._run()
        assert tracker._consecutive_flush_failures >= 2

    async def test_both_new_checks_reach_the_detailed_report(self, monkeypatch):
        checks, details = await health_module._run_extended_checks(_Boom())
        for key in ("report_scheduler", "error_tracker"):
            assert key in checks, f"{key} check exists and nothing calls it"
            assert key in details


class TestTheOeeCalculatorToo:
    """A stalled calculator leaves every OEE figure frozen at its last good value, which
    reads as a quiet shift rather than a broken service."""

    async def test_cycles_failing_repeatedly_is_an_error(self, monkeypatch):
        from app.services import oee_calculator as oc

        monkeypatch.setattr(oc.oee_calculator, "_running", True)
        monkeypatch.setattr(oc.oee_calculator, "_consecutive_failures", 3)
        status, _ = health_module._check_oee_calculator()
        assert status.startswith("error") and "frozen" in status

    async def test_a_working_calculator_is_ok(self, monkeypatch):
        from app.services import oee_calculator as oc

        monkeypatch.setattr(oc.oee_calculator, "_running", True)
        monkeypatch.setattr(oc.oee_calculator, "_consecutive_failures", 0)
        assert health_module._check_oee_calculator()[0] == "ok"

    async def test_per_asset_failures_do_not_trip_it(self):
        """The cycle-level counter must stay untouched when individual assets fail — one
        bad asset starving the check would page on every fleet with one broken machine,
        and per-asset failures already have their own log line."""
        from app.services.oee_calculator import OEECalculator

        calculator = OEECalculator(calculation_interval_minutes=1)
        calculator._running = True
        calculator._asset_states = {"good-asset": {}, "bad-asset": {}}
        calls = {"n": 0}

        async def _mixed(asset_id, time_window_hours=1.0):
            calls["n"] += 1
            if calls["n"] >= 2:
                calculator._running = False
            if asset_id == "bad-asset":
                raise RuntimeError("no telemetry")
            from app.services.oee_calculator import OEEMetrics
            return OEEMetrics(
                availability=1.0, performance=1.0, quality=1.0, oee=1.0,
                planned_time_hours=1.0, runtime_hours=1.0, downtime_hours=0.0,
                total_count=0, good_count=0, scrap_count=0,
            )

        calculator.calculate_oee = _mixed
        calculator._broadcast_oee = lambda *a, **k: _noop()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(calculator, "calculation_interval", 0.0002)
            await calculator._calculation_loop()

        assert calculator._consecutive_failures == 0, (
            "a cycle that completed with one bad asset was counted as a failed cycle"
        )

    async def test_a_cycle_that_fails_outright_is_counted(self):
        """The other direction — and the first mutation run proved it was missing: deleting
        the increment passed every test in this file, because the per-asset test above only
        exercises the success path of the outer handler. A guard for a counter needs a test
        per direction or the counter can half-vanish silently."""
        from app.services.oee_calculator import OEECalculator

        calculator = OEECalculator(calculation_interval_minutes=1)
        calculator._running = True
        calls = {"n": 0}

        class _Detonating(dict):
            """Raises when the cycle iterates it — INSIDE the outer try, unlike a stubbed
            calculate_oee, whose per-asset failures the inner handler absorbs."""

            def __iter__(self):
                calls["n"] += 1
                if calls["n"] >= 3:
                    calculator._running = False
                raise RuntimeError("asset registry unreadable")

        calculator._asset_states = _Detonating()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(calculator, "calculation_interval", 0.0002)
            await calculator._calculation_loop()

        assert calculator._consecutive_failures >= 2


async def _noop():
    return None


class TestThePostingDrainToo:
    """A ledger that stops draining looks exactly like a ledger with nothing to drain."""

    async def test_passes_failing_repeatedly_is_an_error(self, monkeypatch):
        from app.services import posting_drain_scheduler as pd

        monkeypatch.setattr(pd.posting_drain_scheduler, "_running", True)
        monkeypatch.setattr(pd.posting_drain_scheduler, "_consecutive_failures", 3)
        status, _ = health_module._check_posting_drain()
        assert status.startswith("error")

    async def test_disabled_is_its_own_state(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "POSTING_DRAIN_ENABLED", False)
        assert health_module._check_posting_drain()[0] == "disabled"

    async def test_a_pass_where_every_org_fails_counts_as_a_failed_pass(self):
        """THE SEAM ONE LEVEL DOWN. Per-org failures are skipped inside the pass — correct
        tenant isolation — so `drain_all_organizations` RETURNS normally with every org
        broken, and a counter keyed only on the pass raising would read a fleet-wide outage
        as health. The register's own reason for this entry warned that depth alone repeats
        the EdgeAgentBufferHigh mistake; this is the drain-side half of that answer."""
        from app.services.posting_drain_scheduler import PostingDrainScheduler

        scheduler = PostingDrainScheduler()
        scheduler._running = True
        calls = {"n": 0}

        async def _all_orgs_broken():
            calls["n"] += 1
            if calls["n"] >= 2:
                scheduler._running = False
            return {"considered": 0, "posted": 0, "failed": 0, "handed_to_a_person": 0,
                    "orphaned": 0, "organizations": 0, "organizations_failed": 3}

        scheduler.drain_all_organizations = _all_orgs_broken
        with pytest.MonkeyPatch.context() as mp:
            from app.core.config import settings

            mp.setattr(settings, "POSTING_DRAIN_INTERVAL_SECONDS", 0.001)
            await scheduler._run()

        assert scheduler._consecutive_failures >= 2

    async def test_a_pass_with_one_broken_tenant_is_not_a_failed_pass(self):
        """One tenant with an unreachable ERP must not mark the drain broken — that is the
        isolation the per-org skip exists to provide, kept."""
        from app.services.posting_drain_scheduler import PostingDrainScheduler

        scheduler = PostingDrainScheduler()
        scheduler._running = True
        scheduler._consecutive_failures = 4

        async def _one_broken():
            scheduler._running = False
            return {"considered": 5, "posted": 5, "failed": 0, "handed_to_a_person": 0,
                    "orphaned": 0, "organizations": 2, "organizations_failed": 1}

        scheduler.drain_all_organizations = _one_broken
        with pytest.MonkeyPatch.context() as mp:
            from app.core.config import settings

            mp.setattr(settings, "POSTING_DRAIN_INTERVAL_SECONDS", 0.001)
            await scheduler._run()

        assert scheduler._consecutive_failures == 0

    async def test_all_four_new_checks_reach_the_detailed_report(self):
        checks, details = await health_module._run_extended_checks(_Boom())
        for key in ("oee_calculator", "posting_drain"):
            assert key in checks, f"{key} check exists and nothing calls it"
            assert key in details


class TestTheCounterIsActuallyMaintained:
    """The health check is only as good as the state it reads, and that state is written in
    a different file. These drive the real loop bodies.
    """

    async def test_a_raising_iteration_increments_the_counter(self):
        from app.services.command_executor import CommandExecutor

        executor = CommandExecutor()
        executor._running = True
        executor._poll_interval_seconds = 0.01

        calls = {"n": 0}

        async def _boom():
            calls["n"] += 1
            if calls["n"] >= 3:
                executor._running = False
            raise RuntimeError("the database is not answering")

        executor.dispatch_pending = _boom
        await executor._dispatch_loop()

        assert executor._loop_failures["dispatch"] >= 3, (
            "the loop swallowed three failures and recorded none of them, which is the "
            "state in which the old health check answered 'ok'"
        )

    async def test_a_successful_iteration_resets_the_counter(self):
        """Without the reset, a single failure at startup would mark the subsystem broken
        for the lifetime of the process — the opposite failure, and just as misleading."""
        from app.services.command_executor import CommandExecutor

        executor = CommandExecutor()
        executor._running = True
        executor._poll_interval_seconds = 0.01
        executor._loop_failures["dispatch"] = 7

        async def _fine():
            executor._running = False

        executor.dispatch_pending = _fine
        await executor._dispatch_loop()

        assert executor._loop_failures["dispatch"] == 0
