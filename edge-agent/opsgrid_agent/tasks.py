"""Handing a coroutine to the event loop from wherever you happen to be (FS-675).

Two problems, and the second is the one that was costing data.

**A discarded task can vanish.** CPython keeps only a weak reference to a task from the event
loop, so `asyncio.create_task(coro)` with the result thrown away may be collected before it
finishes. The backend had ten of these (FS-674); this agent had six.

**`asyncio.create_task` only works on a thread that is running the loop**, and three of those
six are called from threads that are not:

  * `paho.mqtt` with `loop_start()` dispatches `on_message` from **its own network thread**;
  * `watchdog`'s `Observer` dispatches `on_created` / `on_modified` from **its own thread**.

On those threads `create_task` raises `RuntimeError: no running event loop` before the
coroutine is ever scheduled, so **every message and every file event was lost**. The
coroutine object is left un-awaited, which Python reports as a `RuntimeWarning` nobody reads.

`spawn()` handles all three cases with one call: on the loop it creates a task, off the loop it
uses `run_coroutine_threadsafe` against the loop captured at start, and with no loop available
it says so and closes the coroutine rather than leaving a warning behind. In every case the
reference is retained until completion and a failure is logged.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from typing import Any, Coroutine, Optional, Set, Union

import structlog

logger = structlog.get_logger()

#: Strong references to work in flight, cleared by the done callback.
_INFLIGHT: Set[Union[asyncio.Task, Future]] = set()


def _finished(handle: Union[asyncio.Task, Future]) -> None:
    _INFLIGHT.discard(handle)
    try:
        if handle.cancelled():
            return
        error = handle.exception()
    except asyncio.CancelledError:
        return
    if error is not None:
        logger.error(
            "background_task_failed",
            task=getattr(handle, "get_name", lambda: "unnamed")(),
            error=str(error),
            error_type=type(error).__name__,
        )


def spawn(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> Optional[Union[asyncio.Task, Future]]:
    """Schedule `coro`, from a loop thread or any other thread.

    `loop` is the loop captured when the collector started. It is required whenever this may
    be called from a driver's own thread — paho's network thread, watchdog's observer thread —
    because there is no way to find the loop from there.

    Returns None if there was nowhere to schedule the work, having logged it. The caller gets
    a falsy value rather than an exception: these are message handlers owned by third-party
    libraries, and raising into paho's network loop is not an improvement on losing one
    reading.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    target = running or loop
    if target is None:
        logger.error(
            "background_task_unscheduled",
            task=name,
            detail=(
                "called from a thread with no running loop and no loop was captured at "
                "start; the coroutine cannot be scheduled and is being discarded"
            ),
        )
        coro.close()  # or Python reports 'coroutine was never awaited' and nothing else
        return None

    if running is not None:
        handle: Union[asyncio.Task, Future] = target.create_task(coro, name=name)
    else:
        # Off-loop. This is the path paho and watchdog take, and the one that used to raise.
        handle = asyncio.run_coroutine_threadsafe(coro, target)

    _INFLIGHT.add(handle)
    handle.add_done_callback(_finished)
    return handle


def in_flight() -> int:
    """How much spawned work is outstanding. For tests and the health snapshot."""
    return len(_INFLIGHT)
