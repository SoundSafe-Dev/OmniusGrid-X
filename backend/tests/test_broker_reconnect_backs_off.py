"""The command-ack consumer backs off when the broker is unreachable (FS-474).

The edge agent's FS-472, carried across. `_ack_consumer_loop` has two exits — the consumer
will not start, and the consumer errors mid-stream — and both slept a flat five seconds. A
broker down for a day therefore drew roughly **17,000 connection attempts and 17,000 error
lines**, at a rate that did not depend on anything.

Nothing about it is incorrect, which is why it survived: acks are processed when the broker is
up, the suite is green, and the only symptom is a rate nobody chose. It is the same shape the
agent had, found by asking the agent's newest class of the backend rather than by tripping
over it.

WHY THE VALUES LIVE IN `command_executor.py` AND NOT A POLICY CLASS. The agent has eight
collectors with this loop, so `ReconnectPolicy` earns its place there. The backend has one
loop. Building a framework for a single caller is how a first-pass guess ends up in eight
files — the mistake FS-473 spent a pass undoing. **If a second loop needs these, that is the
moment to factor.**

WHAT THIS ASSERTS. That the delay grows and is bounded, that a successful connection resets
it, and that neither exit sleeps a constant. Not that 1s→60s is the right curve; it is a
first-pass guess like every other reconnect number in this repository.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.services.command_executor import CommandExecutor

SOURCE = Path(inspect.getfile(CommandExecutor)).read_text()


def _fresh() -> CommandExecutor:
    """An executor with only the reconnect state initialised.

    `CommandExecutor.__init__` builds database and broker machinery this test has no use
    for; the backoff is pure arithmetic on one attribute.
    """
    executor = object.__new__(CommandExecutor)
    executor._ack_reconnect_delay = CommandExecutor._ACK_RECONNECT_INITIAL_SECONDS
    return executor


class TestTheCurve:
    def test_it_grows(self):
        executor = _fresh()
        delays = [executor._next_ack_reconnect_delay() for _ in range(5)]
        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0], (
            f"the reconnect delay does not double: {delays}. A flat delay is what made a "
            f"dead broker cost 17,000 attempts a day."
        )

    def test_it_is_bounded(self):
        executor = _fresh()
        for _ in range(30):
            executor._next_ack_reconnect_delay()
        assert executor._next_ack_reconnect_delay() == 60.0, (
            "the delay is unbounded; a long outage would eventually stop retrying often "
            "enough to notice the broker coming back"
        )

    def test_a_successful_connection_resets_it(self):
        """Otherwise one long outage leaves every later blip starting at a minute."""
        executor = _fresh()
        for _ in range(10):
            executor._next_ack_reconnect_delay()
        executor._reset_ack_reconnect_delay()
        assert executor._next_ack_reconnect_delay() == 1.0

    def test_the_first_delay_is_short(self):
        """A broker that bounces should be reconnected to quickly. The backoff is for the
        outage that lasts, not the one that does not."""
        assert CommandExecutor._ACK_RECONNECT_INITIAL_SECONDS <= 2.0


class TestTheLoopUsesIt:
    """Owning a backoff and not sleeping on it is the same as not having one."""

    def _loop_source(self) -> str:
        tree = ast.parse(SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_ack_consumer_loop":
                return ast.get_source_segment(SOURCE, node) or ""
        return ""

    def test_the_loop_exists(self):
        assert self._loop_source(), "_ack_consumer_loop not found; this test checks nothing"

    def test_neither_exit_sleeps_a_constant(self):
        """BOTH exits. The defect had two, and fixing one would have left a broker that
        errors mid-stream retrying at a flat rate while a broker that never starts backed
        off properly — a difference nobody would ever notice.

        THE RECONNECT PATHS ONLY. The first version of this check flagged every constant
        sleep in the loop and caught `await asyncio.sleep(1)` inside the per-message
        handler, which seeks back to the offset and pauses before re-entering — a
        legitimate pause after ONE message failed, nothing to do with reaching the broker.
        A guard that cannot tell those apart reports a defect where there is none, and the
        next person turns it off.

        The distinction is structural: reconnect handling sits at the top level of the
        `while` body, and per-message handling sits inside the `async for`.
        """
        tree = ast.parse(self._loop_source())

        inside_message_loop = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFor, ast.For)):
                for inner in ast.walk(node):
                    inside_message_loop.add(id(inner))

        constants = [
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") == "sleep"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and id(node) not in inside_message_loop
        ]
        assert not constants, (
            f"the ack consumer loop sleeps constant(s) {constants} on a reconnect path. "
            f"Use `_next_ack_reconnect_delay()` so a broker that stays down is dialled "
            f"less often, not exactly as often."
        )

    def test_it_calls_the_backoff_and_the_reset(self):
        loop = self._loop_source()
        assert "_next_ack_reconnect_delay()" in loop, (
            "the loop never advances the backoff, so every retry waits the same amount"
        )
        assert "_reset_ack_reconnect_delay()" in loop, (
            "the loop never resets after a successful connection, so one long outage "
            "leaves every later blip starting at the cap"
        )


class TestTheValuesAreNotSpreadAround:
    """Rule 98, applied to the fix itself.

    FS-473 spent a pass undoing a guess that had been copied into eight files. These two
    constants exist in one class for one loop; a second copy is the beginning of the same
    problem, and the remedy at that point is to factor rather than to copy again.
    """

    def test_the_constants_are_declared_once(self):
        assert SOURCE.count("_ACK_RECONNECT_INITIAL_SECONDS = ") == 1
        assert SOURCE.count("_ACK_RECONNECT_CAP_SECONDS = ") == 1

    def test_no_other_backend_module_declares_them(self):
        app = Path(inspect.getfile(CommandExecutor)).resolve().parent.parent
        offenders = [
            str(path.relative_to(app.parent))
            for path in sorted(app.rglob("*.py"))
            if path.name != "command_executor.py"
            and "_ACK_RECONNECT" in path.read_text()
        ]
        assert not offenders, (
            f"these modules also declare the ack reconnect constants: {offenders}. Two "
            f"copies of a tuning value is how the edge agent ended up with sixteen."
        )
