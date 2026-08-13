"""Background tasks that cannot vanish and cannot fail in silence (FS-674).

`asyncio.create_task(coro)` on its own has two holes, and this codebase had ten of them.

**The event loop keeps only a WEAK reference to a task.** CPython's own documentation says it
plainly: *"Save a reference to the result of this function, to avoid a task disappearing
mid-execution ... A task that isn't referenced elsewhere may get garbage collected at any time,
even before it's done."* So a discarded `create_task` is work that may simply not happen, with
no error and no log line — including `edge_ingest`, which fired one per request to forward
accepted readings to the broker.

**An exception inside a task is never retrieved.** It surfaces as asyncio's own
*"Task exception was never retrieved"* at garbage-collection time, on the `asyncio` logger
rather than the structured one, attached to no request and no trace id. This is the backend
twin of the frontend rejection that sat unowned under a green test run (FS-673): the same
defect — a failure whose owner is nobody — wearing a different runtime's clothes.

`spawn()` closes both. The task is held in a module-level set until it finishes, and its
result is inspected on completion so an exception is logged where the rest of this service's
errors are logged.

WHAT THIS IS NOT. It is not supervision: nothing is retried and nothing is restarted. A loop
that dies stays dead, exactly as before — the difference is that now you find out.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine, Set

import structlog

logger = structlog.get_logger()

#: Strong references to in-flight tasks. The only reason this exists is the weak-reference
#: rule above; entries are removed by the done callback, so it holds exactly the live set.
_BACKGROUND: Set[asyncio.Task] = set()


def _finished(task: asyncio.Task) -> None:
    _BACKGROUND.discard(task)
    if task.cancelled():
        # Cancellation is how shutdown works here; it is not a failure.
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "background_task_failed",
            task=task.get_name(),
            error=str(error),
            error_type=type(error).__name__,
            exc_info=error,
        )


def spawn(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task:
    """Start `coro` as a background task that is referenced and whose failure is logged.

    `name` is required rather than optional. An unnamed task logs as `Task-17`, which
    identifies nothing at three in the morning, and the whole point of this function is that
    the log line is the only evidence the work ever existed.
    """
    task = asyncio.create_task(coro, name=name)
    _BACKGROUND.add(task)
    task.add_done_callback(_finished)
    return task


def in_flight() -> int:
    """How many spawned tasks are still running. For tests and health surfaces."""
    return len(_BACKGROUND)
