"""A circuit breaker for outbound dependencies (FS-846/847/848).

WHY. When a dependency is down, every caller pays its full connect timeout before failing.
That is the mechanism by which one dead service takes an API with it: each request holds a
worker, a database connection and a bulkhead slot for the length of a TCP timeout, and the
platform runs out of those long before the dependency comes back. A breaker converts the
second and subsequent failures into an immediate, cheap refusal.

THE ONE THAT ALREADY EXISTED is `services/erp_connector_base.py`, welded to that class and
usable by nothing else — which is why five Redpanda producers and six Redis clients were
built without one. This is the same idea as a primitive.

WHAT A BREAKER IS NOT. It does not make a dependency work, and opening one is a decision
to fail faster rather than to fail less. That is right for a dependency the caller can do
without (`feature_flags` has documented defaults, the rate limiter has an in-memory
fallback) and it is a judgement call for one it cannot. The caller decides by choosing
what to do when `CircuitOpen` is raised; this class never decides that for them.

HALF-OPEN IS ONE TRIAL, NOT A WINDOW. After `recovery_seconds` a single call is allowed
through. If it succeeds the breaker closes; if it fails the breaker re-opens and the clock
restarts. Letting a burst through on recovery is how a breaker turns a recovering
dependency back into a dead one.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, TypeVar

import structlog
from prometheus_client import Counter, Gauge

logger = structlog.get_logger()

T = TypeVar("T")

CIRCUIT_STATE = Gauge(
    "opsgrid_circuit_breaker_state",
    "0 closed, 1 half-open, 2 open",
    ["dependency"],
)

CIRCUIT_TRIPS = Counter(
    "opsgrid_circuit_breaker_trips_total",
    "Times a breaker moved from closed to open",
    ["dependency"],
)

CIRCUIT_REJECTIONS = Counter(
    "opsgrid_circuit_breaker_rejections_total",
    "Calls refused without being attempted because the breaker was open",
    ["dependency"],
)

_CLOSED, _HALF_OPEN, _OPEN = "closed", "half_open", "open"
_STATE_VALUE = {_CLOSED: 0, _HALF_OPEN: 1, _OPEN: 2}


class CircuitOpen(Exception):
    """The dependency is presumed down and the call was not attempted."""

    def __init__(self, dependency: str, retry_in: float) -> None:
        self.dependency = dependency
        self.retry_in = retry_in
        super().__init__(
            f"{dependency} circuit is open; not attempting the call. "
            f"Retrying in ~{retry_in:.0f}s."
        )


class CircuitBreaker:
    """Trip after `failure_threshold` consecutive failures; retry after `recovery_seconds`.

    CONSECUTIVE, not a rate. A rate needs a window and a decision about what fraction is
    "too many", and both are tuning knobs nobody revisits. Consecutive failures answer the
    question a breaker actually asks — *is this dependency responding at all* — and reset
    on the first success, so intermittent errors never trip it.
    """

    def __init__(
        self,
        dependency: str,
        *,
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.dependency = dependency
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_seconds = recovery_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._state = _CLOSED
        self._lock = asyncio.Lock()
        CIRCUIT_STATE.labels(dependency=dependency).set(0)

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str) -> None:
        self._state = state
        CIRCUIT_STATE.labels(dependency=self.dependency).set(_STATE_VALUE[state])

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run `fn`, or raise `CircuitOpen` without running it.

        The lock covers the STATE DECISION only, never the call itself. Holding it across
        the call would serialise every request through the dependency — turning a breaker
        meant to protect throughput into the thing that destroys it.
        """
        async with self._lock:
            if self._state == _OPEN:
                assert self._opened_at is not None
                elapsed = self._clock() - self._opened_at
                if elapsed < self.recovery_seconds:
                    CIRCUIT_REJECTIONS.labels(dependency=self.dependency).inc()
                    raise CircuitOpen(self.dependency, self.recovery_seconds - elapsed)
                # One trial call, and only one: the state moves to half-open here, so a
                # concurrent caller arriving now sees half_open and is refused below
                # rather than joining a stampede onto a dependency that may still be down.
                self._set_state(_HALF_OPEN)
                logger.info("circuit_half_open", dependency=self.dependency)
            elif self._state == _HALF_OPEN:
                CIRCUIT_REJECTIONS.labels(dependency=self.dependency).inc()
                raise CircuitOpen(self.dependency, self.recovery_seconds)

        try:
            result = await fn()
        except Exception:
            await self._record_failure()
            raise
        await self._record_success()
        return result

    async def _record_success(self) -> None:
        async with self._lock:
            if self._state != _CLOSED:
                logger.info("circuit_closed", dependency=self.dependency)
            self._failures = 0
            self._opened_at = None
            self._set_state(_CLOSED)

    async def _record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            # A failed trial re-opens immediately and restarts the clock, rather than
            # counting toward the threshold again — the dependency has just told us it is
            # still down, and there is nothing to accumulate.
            if self._state == _HALF_OPEN or self._failures >= self.failure_threshold:
                if self._state != _OPEN:
                    CIRCUIT_TRIPS.labels(dependency=self.dependency).inc()
                    logger.warning(
                        "circuit_opened",
                        dependency=self.dependency,
                        consecutive_failures=self._failures,
                    )
                self._opened_at = self._clock()
                self._set_state(_OPEN)
