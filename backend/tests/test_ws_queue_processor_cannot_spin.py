"""The websocket queue processor must not hot-spin on a persistent failure.

`_process_message_queue` caught every exception, logged it, and re-entered the loop
immediately. With a TRANSIENT fault that is fine. With a PERMANENT one it is a bug
with no exit: the loop raises on entry, logs, and retries at full CPU forever.

The permanent case is real and reachable. `asyncio.Queue` binds its internal futures
to the first event loop that awaits them; the manager is a module-level singleton, so
a second loop in the same process makes every `get()` raise
``RuntimeError: ... is bound to a different event loop``. Found by the API contract
suite (task 12), where every generated example runs on a fresh ASGI event loop: after
the first one, this task spun and the test never returned. That is what made an
operation appear to "hang" for 10+ minutes.

Two properties are pinned here, one per failure kind:
  * a permanent loop-binding error STOPS the processor instead of retrying;
  * a repeating transient error SLEEPS between attempts instead of spinning.
"""

import asyncio

import pytest

from app.services.websocket_manager import WebSocketManager


@pytest.mark.asyncio
async def test_a_wrong_loop_error_stops_the_processor():
    """The permanent failure must terminate the loop, not retry it."""
    manager = WebSocketManager()
    manager._running = True

    attempts = 0

    class WrongLoopQueue:
        async def get(self):
            nonlocal attempts
            attempts += 1
            raise RuntimeError(
                "<Queue at 0x0 maxsize=10000> is bound to a different event loop"
            )

    manager._message_queue = WrongLoopQueue()

    # No timeout guard: if the fix regresses, this never returns and the failure is a
    # hang — which is exactly the symptom being prevented. wait_for turns that into a
    # readable failure instead.
    await asyncio.wait_for(manager._process_message_queue(), timeout=5)

    assert attempts == 1, (
        f"the processor retried a permanent failure {attempts} times; a queue bound to "
        "another event loop can never succeed, so retrying is a CPU spin"
    )


@pytest.mark.asyncio
async def test_a_repeating_transient_error_backs_off_instead_of_spinning():
    """The transient failure may retry, but must not retry without delay."""
    manager = WebSocketManager()
    manager._running = True

    attempts = 0

    class FlakyQueue:
        async def get(self):
            nonlocal attempts
            attempts += 1
            if attempts >= 6:
                manager._running = False
            raise ValueError("transient failure")

    manager._message_queue = FlakyQueue()

    started = asyncio.get_event_loop().time()
    await asyncio.wait_for(manager._process_message_queue(), timeout=10)
    elapsed = asyncio.get_event_loop().time() - started

    assert attempts >= 5
    # Five failures with the 0.1s-doubling backoff is ~1.5s. Asserting only that real
    # time passed keeps this from becoming a brittle assertion on the exact curve,
    # while still failing outright if the sleep is ever removed.
    assert elapsed > 0.5, (
        f"{attempts} consecutive failures took only {elapsed:.3f}s — the error path is "
        "not sleeping, so a persistent fault would burn a core"
    )


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed_as_an_error():
    """Shutdown must propagate, not be caught by the retry path.

    `except Exception` does not catch CancelledError on Python 3.8+, but the handler
    is explicit about it and this pins that: if the ordering is ever changed so a bare
    handler comes first, a cancelled processor would be logged as an error and retried,
    and shutdown would hang.
    """
    manager = WebSocketManager()
    manager._running = True

    class CancellingQueue:
        async def get(self):
            raise asyncio.CancelledError()

    manager._message_queue = CancellingQueue()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(manager._process_message_queue(), timeout=5)
