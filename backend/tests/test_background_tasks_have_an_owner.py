"""A background task nobody holds and nobody watches (FS-674).

Ten `asyncio.create_task(...)` calls in `app/` discarded the task they created. Two holes,
both documented, neither visible:

  * **The event loop keeps only a WEAK reference.** CPython's docs: *"Save a reference to the
    result of this function, to avoid a task disappearing mid-execution ... may get garbage
    collected at any time, even before it's done."* A discarded task is work that may simply
    not happen. `edge_ingest` fired one **per request** to forward accepted readings to the
    broker, on a path whose response has already told the agent how many were forwarded.
  * **An exception is never retrieved.** It appears as asyncio's own *"Task exception was
    never retrieved"* at garbage-collection time, on the `asyncio` logger rather than the
    structured one, attached to no request and no trace id.

This is the backend twin of FS-673 — a frontend rejection that sat unowned under a green test
run — and it was found by carrying that class across runtimes rather than by reading. Same
defect, different clothes: a failure whose owner is nobody.

THE SPLIT WAS TEN AND TEN. The other ten already assign to `self._task`, which makes them the
negative control and is why this file does not simply ban `create_task`: retaining the
reference is the property, and `spawn` is one way to have it.

WHAT IS NOT CLAIMED. `spawn` is not supervision. Nothing is retried, nothing is restarted, and
a loop that dies stays dead — the difference is that you find out.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

from app.core.tasks import _BACKGROUND, in_flight, spawn

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: `create_task` calls allowed to remain, with the reason. `app/core/tasks.py` is the
#: implementation of the fix and cannot use itself.
ALLOWED = {"core/tasks.py": "the implementation of spawn(); the retention happens here"}


def _sites():
    """(path, line, retained) for every `*.create_task(...)` call statement in `app/`."""
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text())
        seen = set()
        for parent in ast.walk(tree):
            for _field, value in ast.iter_fields(parent):
                for child in value if isinstance(value, list) else [value]:
                    if not isinstance(child, ast.stmt):
                        continue
                    call = getattr(child, "value", None)
                    if not isinstance(call, ast.Call):
                        continue
                    func = call.func
                    if not (isinstance(func, ast.Attribute) and func.attr == "create_task"):
                        continue
                    if child.lineno in seen:
                        continue
                    seen.add(child.lineno)
                    # A bare `Expr` statement throws the task away. An `Assign` keeps it.
                    yield (
                        str(path.relative_to(APP)),
                        child.lineno,
                        not isinstance(child, ast.Expr),
                    )


class TestTheSweepIsReal:
    def test_create_task_sites_are_found(self):
        sites = list(_sites())
        assert len(sites) >= 8, (
            f"only {len(sites)} create_task sites found; the AST walk has stopped "
            f"descending and the assertion below is about nothing"
        )

    def test_the_retained_sites_are_the_negative_control(self):
        """Ten sites already assign to `self._task`. If that number collapses, the walk is
        misreading assignments as discards and would report the whole tree as broken."""
        retained = [s for s in _sites() if s[2]]
        assert len(retained) >= 8, (
            f"only {len(retained)} create_task results are retained; an `Assign` is being "
            f"read as an `Expr` and this guard is now calling correct code wrong"
        )

    def test_a_discarded_call_is_recognised(self):
        """Positive control, in the shape that shipped."""
        tree = ast.parse("async def f():\n    asyncio.create_task(g())\n")
        discarded = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Attribute)
            and n.value.func.attr == "create_task"
        ]
        assert discarded

    def test_the_allowlist_entries_still_exist(self):
        """An allowlist for a file that has moved is an exemption nobody can audit."""
        for entry in ALLOWED:
            assert (APP / entry).exists(), f"{entry} is allowlisted and does not exist"


def test_no_background_task_is_created_and_discarded():
    discarded = sorted(
        f"{path}:{line}" for path, line, retained in _sites() if not retained and path not in ALLOWED
    )
    assert not discarded, (
        f"{discarded}\n\n"
        f"The event loop holds only a weak reference to a task, so a discarded one may be "
        f"garbage-collected mid-execution — the work silently does not happen. An exception "
        f"inside it is also never retrieved, surfacing as asyncio's own "
        f"'Task exception was never retrieved' at GC time rather than in the structured log. "
        f"Use `app.core.tasks.spawn(coro, name=...)`, or assign the task to something that "
        f"outlives it."
    )


class TestSpawnDoesBothJobs:
    """The guard checks the SHAPE. These check that the shape is worth having — a helper
    everything was migrated to, whose own behaviour nothing asserted, would be a rename."""

    @pytest.mark.asyncio
    async def test_the_task_is_referenced_while_it_runs(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def work():
            started.set()
            await release.wait()

        before = in_flight()
        task = spawn(work(), name="test.referenced")
        await started.wait()
        assert task in _BACKGROUND, (
            "the task is not held anywhere, so the event loop's weak reference is the only "
            "one and it may be collected mid-execution"
        )
        assert in_flight() == before + 1
        release.set()
        await task

    @pytest.mark.asyncio
    async def test_the_reference_is_released_when_it_finishes(self):
        """The other direction: a set that only grows is a leak, and a long-lived process
        firing one of these per request would grow it forever."""
        before = in_flight()
        task = spawn(asyncio.sleep(0), name="test.released")
        await task
        await asyncio.sleep(0)  # let the done callback run
        assert task not in _BACKGROUND
        assert in_flight() == before

    @pytest.mark.asyncio
    async def test_a_failure_is_logged_rather_than_lost(self):
        """`structlog.testing.capture_logs`, not `caplog` — caplog sees nothing because
        structlog renders through its own processor chain, and `capfd` passes alone but
        fails in the full suite where another module has already reconfigured the sink.
        `test_unknown_reference_is_a_client_error.py` learned this first; the same seam
        caught this file on its first run."""
        import structlog

        async def explode():
            raise RuntimeError("the broker is gone")

        with structlog.testing.capture_logs() as logs:
            task = spawn(explode(), name="test.failing")
            with pytest.raises(RuntimeError):
                await task
            await asyncio.sleep(0)

        failures = [entry for entry in logs if entry.get("event") == "background_task_failed"]
        assert failures, (
            "a task raised and nothing recorded it; the exception is now waiting to be "
            "reported by the garbage collector, on a different logger, with no trace id"
        )
        assert failures[0]["error"] == "the broker is gone"
        assert failures[0]["task"] == "test.failing"

    @pytest.mark.asyncio
    async def test_cancellation_is_not_reported_as_a_failure(self):
        """Cancellation is how shutdown works here. A helper that logged an error for every
        cancelled loop would make every clean shutdown look like a crash, and the next
        person would stop reading the log line that matters."""
        import structlog

        started = asyncio.Event()

        async def forever():
            started.set()
            await asyncio.sleep(3600)

        with structlog.testing.capture_logs() as logs:
            task = spawn(forever(), name="test.cancelled")
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)

        assert not [e for e in logs if e.get("event") == "background_task_failed"]

    @pytest.mark.asyncio
    async def test_the_task_carries_the_name_it_was_given(self):
        """`Task-17` identifies nothing at three in the morning, and the log line is the
        only evidence this work ever existed."""
        task = spawn(asyncio.sleep(0), name="edge_ingest.forward")
        assert task.get_name() == "edge_ingest.forward"
        await task
