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
