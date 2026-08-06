"""Resilience primitives for edge agent collectors.

Two composable building blocks, and one policy that decides how they are tuned. Used by
**every collector that reconnects to a device** — three since they were written, and five
more since FS-472 found them retrying a switched-off PLC every five seconds forever:

* :class:`ExponentialBackoff` — increases the delay between retries so
  the collector stops hammering a struggling service. Resets on success.
* :class:`CircuitBreaker` — stops attempting an operation entirely after
  repeated failures, giving the downstream service a window to recover.

Both classes are pure Python with no external dependencies and no async
behaviour. The caller controls the actual sleeping, which keeps the
primitives reusable across async, threaded, or synchronous contexts.

Usage::

    backoff = ExponentialBackoff(initial=1.0, cap=60.0, multiplier=2.0)
    breaker = CircuitBreaker(
        failure_threshold=5,
        initial_cooldown=30.0,
        cooldown_cap=300.0,
        cooldown_multiplier=2.0,
    )

    while running:
        if not breaker.allow():
            await asyncio.sleep(breaker.time_until_retry())
            continue

        try:
            await connect_to_service()
            backoff.reset()
            breaker.record_success()
        except ConnectionError:
            breaker.record_failure()
            await asyncio.sleep(backoff.next_delay())

* :class:`ReconnectPolicy` — the tuning, in one place. The two primitives take seven
  numbers between them; those numbers used to be written inline in eight collectors, which
  made a first-pass guess into something nobody could revise (FS-473). A collector now asks
  the policy for a matched pair, and a ``reconnect:`` block in its config overrides them per
  site.

Run ``python -m opsgrid_agent.resilience`` from ``edge-agent/`` to see
a self-contained behavioural demo of both primitives.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Callable, Optional

import structlog

logger = structlog.get_logger()


# --------------------------------------------------------------------------- #
# Exponential backoff
# --------------------------------------------------------------------------- #


class ExponentialBackoff:
    """Compute exponentially increasing delays between retry attempts.

    The first call to :meth:`next_delay` returns ``initial`` seconds, the
    second returns ``initial * multiplier``, and so on, capped at ``cap``.
    Calling :meth:`reset` returns the next delay to ``initial`` — use
    this after a successful operation.

    This class only computes the delay value; the caller is responsible
    for actually sleeping.

    Args:
        initial: First delay in seconds. Must be > 0.
        cap: Maximum delay in seconds. Must be >= initial.
        multiplier: Factor applied to the current delay after each call
            to :meth:`next_delay`. Must be > 1.

    Raises:
        ValueError: If any argument violates its constraint.
    """

    def __init__(
        self,
        initial: float = 1.0,
        cap: float = 60.0,
        multiplier: float = 2.0,
    ):
        if initial <= 0:
            raise ValueError(f"initial must be > 0, got {initial}")
        if cap < initial:
            raise ValueError(f"cap ({cap}) must be >= initial ({initial})")
        if multiplier <= 1:
            raise ValueError(f"multiplier must be > 1, got {multiplier}")

        self.initial = initial
        self.cap = cap
        self.multiplier = multiplier
        self._current = initial

    def next_delay(self) -> float:
        """Return the current delay (seconds) and advance for the next call."""
        delay = self._current
        self._current = min(self._current * self.multiplier, self.cap)
        return delay

    def reset(self) -> None:
        """Reset the delay to ``initial``. Call after a successful operation."""
        self._current = self.initial

    @property
    def current_delay(self) -> float:
        """The delay that the next call to :meth:`next_delay` will return."""
        return self._current


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #


class CircuitState(Enum):
    """State of a :class:`CircuitBreaker`."""

    CLOSED = "closed"        # Normal operation; requests pass through.
    OPEN = "open"            # Too many failures; requests rejected.
    HALF_OPEN = "half_open"  # Cooldown elapsed; one probe allowed.


class CircuitBreaker:
    """Three-state circuit breaker that protects against cascading failures.

    State machine:

    * **CLOSED** (initial): requests pass through. Consecutive failures
      are counted; on reaching ``failure_threshold`` the breaker
      transitions to OPEN.
    * **OPEN**: requests are rejected immediately. After the current
      cooldown elapses, the next call to :meth:`allow` transitions the
      breaker to HALF_OPEN.
    * **HALF_OPEN**: one probe request is allowed. The next reported
      outcome decides:

      - :meth:`record_success` → CLOSED, all state reset.
      - :meth:`record_failure` → OPEN with the cooldown multiplied by
        ``cooldown_multiplier`` (capped at ``cooldown_cap``).

    The breaker only tracks state. The caller is responsible for honoring
    :meth:`allow` and reporting outcomes via :meth:`record_success` and
    :meth:`record_failure`.

    Defaults are deliberately conservative for first-instance-of-pattern
    rollout. Tune via :class:`ReconnectPolicy` below, which every collector now takes its
    values from, or per site with a ``reconnect:`` block in that collector's config.

    This used to say "see the ``TODO(tune)`` notes in each collector", which was accurate
    while eight collectors each carried their own copy of the numbers. They do not (FS-473),
    and a cross-reference that survives the thing it points at is how a reader ends up
    editing a file that no longer decides anything.

    Args:
        failure_threshold: Consecutive failures in CLOSED state required
            to transition to OPEN.
        initial_cooldown: First OPEN-state cooldown in seconds.
        cooldown_cap: Maximum OPEN-state cooldown in seconds.
        cooldown_multiplier: Factor applied to the cooldown when a
            HALF_OPEN probe fails.
        name: Identifier used in log events for observability.
        time_source: Callable returning monotonic seconds. Defaults to
            ``time.monotonic``; override for testability.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        initial_cooldown: float = 30.0,
        cooldown_cap: float = 300.0,
        cooldown_multiplier: float = 2.0,
        name: str = "breaker",
        time_source: Callable[[], float] = time.monotonic,
    ):
        if failure_threshold < 1:
            raise ValueError(
                f"failure_threshold must be >= 1, got {failure_threshold}"
            )
        if initial_cooldown <= 0:
            raise ValueError(
                f"initial_cooldown must be > 0, got {initial_cooldown}"
            )
        if cooldown_cap < initial_cooldown:
            raise ValueError(
                f"cooldown_cap ({cooldown_cap}) must be >= "
                f"initial_cooldown ({initial_cooldown})"
            )
        if cooldown_multiplier <= 1:
            raise ValueError(
                f"cooldown_multiplier must be > 1, got {cooldown_multiplier}"
            )

        self.failure_threshold = failure_threshold
        self.initial_cooldown = initial_cooldown
        self.cooldown_cap = cooldown_cap
        self.cooldown_multiplier = cooldown_multiplier
        self.name = name
        self._time = time_source

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._current_cooldown = initial_cooldown
        self._opened_at: Optional[float] = None

    @property
    def state(self) -> CircuitState:
        """The current state.

        Note that :meth:`allow` may transition the state from OPEN to
        HALF_OPEN as a side effect; read this property *after* calling
        :meth:`allow` if you need the post-call state.
        """
        return self._state

    def allow(self) -> bool:
        """Return True if a request may be attempted.

        Side effect: if the breaker is OPEN and its cooldown has
        elapsed, this call transitions the breaker to HALF_OPEN before
        returning True.
        """
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.HALF_OPEN:
            return True

        assert self._opened_at is not None
        if self._time() - self._opened_at >= self._current_cooldown:
            self._transition_to(CircuitState.HALF_OPEN)
            return True

        return False

    def time_until_retry(self) -> float:
        """Seconds until the next attempt is allowed.

        Returns 0.0 if the breaker is CLOSED, HALF_OPEN, or OPEN with an
        already-elapsed cooldown. When OPEN with cooldown remaining,
        returns the remaining wait.
        """
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return 0.0
        elapsed = self._time() - self._opened_at
        return max(0.0, self._current_cooldown - elapsed)

    def record_success(self) -> None:
        """Report a successful operation.

        * CLOSED: resets the failure counter.
        * HALF_OPEN: transitions to CLOSED and resets all state.
        * OPEN: logged as a contract violation but otherwise ignored.
        """
        if self._state == CircuitState.CLOSED:
            self._failure_count = 0
            return

        if self._state == CircuitState.HALF_OPEN:
            self._failure_count = 0
            self._current_cooldown = self.initial_cooldown
            self._opened_at = None
            self._transition_to(CircuitState.CLOSED)
            return

        logger.warning(
            "circuit_breaker_success_while_open",
            name=self.name,
        )

    def record_failure(self) -> None:
        """Report a failed operation.

        * CLOSED: increments the failure counter; transitions to OPEN if
          the counter reaches ``failure_threshold``.
        * HALF_OPEN: probe failed — multiplies the cooldown (capped) and
          transitions back to OPEN.
        * OPEN: ignored (the caller violated the contract by attempting
          a request the breaker rejected).
        """
        if self._state == CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._open()
            return

        if self._state == CircuitState.HALF_OPEN:
            self._current_cooldown = min(
                self._current_cooldown * self.cooldown_multiplier,
                self.cooldown_cap,
            )
            self._open()
            return

    def _open(self) -> None:
        """Transition to OPEN, recording the open time."""
        self._opened_at = self._time()
        self._transition_to(CircuitState.OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        """Log and apply a state transition."""
        if self._state == new_state:
            return
        old_state = self._state
        self._state = new_state
        logger.info(
            "circuit_breaker_state_change",
            name=self.name,
            from_state=old_state.value,
            to_state=new_state.value,
            failure_count=self._failure_count,
            current_cooldown=self._current_cooldown,
        )


# --------------------------------------------------------------------------- #
# Self-contained demo
# --------------------------------------------------------------------------- #


class ReconnectPolicy:
    """How hard a collector retries a device it cannot reach (FS-473).

    THE NUMBERS LIVED IN EIGHT FILES. `modbus`, `opcua` and `mqtt` each constructed a
    backoff and a breaker inline; FS-472 gave the same treatment to five more collectors by
    copying the same four constants into each. Sixteen occurrences of `cap=60.0` and
    `failure_threshold=5` across eight modules, and a `TODO(tune)` comment in one of them
    explaining that they were a first-pass guess pending production telemetry.

    A guess in one place is a guess. A guess in eight places is a guess nobody can revise:
    the person with the telemetry has to find all eight, and the ones they miss are the ones
    that keep the old behaviour.

    **So the defaults live here, once, and they are still the same first-pass guess.** This
    class does not make them right — it makes them changeable, and it makes a per-site
    override possible without editing any collector.

    WHY A CLASS RATHER THAN MODULE CONSTANTS. `instruments()` returns a matched pair. A
    backoff whose cap exceeds the breaker's cooldown means the breaker never gets to do
    anything, and two loose constants invite exactly that mismatch; `__post_init__` refuses
    it.
    """

    # TODO(tune): a first-pass conservative guess, carried here from
    # `modbus_collector.py` where it was written (FS-473). Revisit once there is production
    # telemetry on real controller outage patterns. Changing them here changes all eight
    # collectors, which is the point — and a single site can override with a `reconnect:`
    # block rather than waiting for this.

    #: Delay before the first retry, and the ceiling the doubling reaches.
    initial_delay: float = 1.0
    max_delay: float = 60.0
    multiplier: float = 2.0

    #: Consecutive failures before the breaker opens, and how long it then waits.
    failure_threshold: int = 5
    initial_cooldown: float = 30.0
    cooldown_cap: float = 300.0
    cooldown_multiplier: float = 2.0

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
        failure_threshold: int = 5,
        initial_cooldown: float = 30.0,
        cooldown_cap: float = 300.0,
        cooldown_multiplier: float = 2.0,
    ) -> None:
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.failure_threshold = failure_threshold
        self.initial_cooldown = initial_cooldown
        self.cooldown_cap = cooldown_cap
        self.cooldown_multiplier = cooldown_multiplier

        # The pair has to make sense together. A backoff that climbs past the breaker's
        # cooldown cap means the breaker opens and the loop was already waiting longer than
        # the cooldown, so opening changes nothing — the instrument is present and inert,
        # which is the failure mode this repository has a rule about.
        if self.max_delay > self.cooldown_cap:
            raise ValueError(
                f"max_delay ({self.max_delay}) exceeds cooldown_cap ({self.cooldown_cap}); "
                f"the breaker would never slow anything down"
            )

    @classmethod
    def from_settings(cls, settings: Optional[dict]) -> "ReconnectPolicy":
        """Build from the `reconnect:` block itself.

        Two entry points because the collectors take their configuration two ways: the
        older three (`modbus`, `opcua`, `mqtt`) are constructed with explicit keyword
        arguments by the coordinator, and the rest receive a config dict. Both reach the
        same validation, so a `reconnect:` block in YAML behaves identically either way —
        which is the point, since an operator writing the file cannot see the difference.
        """
        return cls.from_config({"reconnect": settings})

    @classmethod
    def from_config(cls, config: Optional[dict]) -> "ReconnectPolicy":
        """Build from a collector's `reconnect:` block, falling back to the defaults.

        Unknown keys are REJECTED rather than ignored. A typo in a YAML key that silently
        keeps the default is the shape of every config defect in this repository: the
        operator believes they tuned it, and nothing says otherwise.
        """
        settings = (config or {}).get("reconnect") or {}
        if not isinstance(settings, dict):
            raise ValueError(f"`reconnect` must be a mapping, got {type(settings).__name__}")

        known = {
            "initial_delay", "max_delay", "multiplier",
            "failure_threshold", "initial_cooldown", "cooldown_cap", "cooldown_multiplier",
        }
        unknown = sorted(set(settings) - known)
        if unknown:
            raise ValueError(
                f"unknown reconnect settings {unknown}; known keys are {sorted(known)}"
            )
        return cls(**settings)

    def instruments(self, name: str) -> tuple[ExponentialBackoff, CircuitBreaker]:
        """The matched pair a reconnect loop needs, named for its log lines."""
        backoff = ExponentialBackoff(
            initial=self.initial_delay, cap=self.max_delay, multiplier=self.multiplier
        )
        breaker = CircuitBreaker(
            failure_threshold=self.failure_threshold,
            initial_cooldown=self.initial_cooldown,
            cooldown_cap=self.cooldown_cap,
            cooldown_multiplier=self.cooldown_multiplier,
            name=name,
        )
        return backoff, breaker


def _demo() -> None:
    """Print a behavioural demonstration of the resilience primitives.

    Run with::

        cd edge-agent
        python -m opsgrid_agent.resilience
    """
    print("=" * 60)
    print("Demo 1: ExponentialBackoff(initial=0.5, cap=4.0, multiplier=2)")
    print("=" * 60)
    backoff = ExponentialBackoff(initial=0.5, cap=4.0, multiplier=2.0)
    print("Sequence of next_delay() calls:")
    for i in range(8):
        print(f"  attempt {i + 1}: {backoff.next_delay()}s")
    backoff.reset()
    print("After reset():")
    print(f"  attempt 1: {backoff.next_delay()}s")
    print()

    print("=" * 60)
    print("Demo 2: CircuitBreaker(threshold=3, cooldown=0.5s, cap=4.0s, x2)")
    print("=" * 60)

    # Use a controllable clock so the demo runs instantly.
    fake_now = [0.0]

    def fake_time() -> float:
        return fake_now[0]

    breaker = CircuitBreaker(
        failure_threshold=3,
        initial_cooldown=0.5,
        cooldown_cap=4.0,
        cooldown_multiplier=2.0,
        name="demo",
        time_source=fake_time,
    )

    def show(label: str) -> None:
        allowed = breaker.allow()
        print(
            f"  [{label}] state={breaker.state.value}, "
            f"allow={allowed}, "
            f"time_until_retry={breaker.time_until_retry():.2f}s"
        )

    show("start")
    breaker.record_failure(); show("failure 1")
    breaker.record_failure(); show("failure 2")
    breaker.record_failure(); show("failure 3 - should open")
    fake_now[0] += 0.6
    show("clock+0.6s - allow() promotes to half-open")
    breaker.record_failure(); show("probe failed - reopen with longer cooldown")
    fake_now[0] += 1.1
    show("clock+1.1s - allow() promotes to half-open again")
    breaker.record_success(); show("probe succeeded - closed, state reset")
    print()


if __name__ == "__main__":
    _demo()
