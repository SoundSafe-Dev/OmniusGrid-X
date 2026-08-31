"""The breaker opens, refuses cheaply, and recovers on one trial (FS-846/847/848).

WHY THIS MATTERS MORE THAN IT LOOKS. When a dependency is down, every caller pays its full
connect timeout before failing — so each request holds a worker, a database connection and
a bulkhead slot for the length of a TCP timeout. The platform runs out of those long
before the dependency comes back, which is how one dead service takes an API with it. A
breaker turns the second and subsequent failures into an immediate refusal.

The clock is injected, so nothing here sleeps: a breaker test that waits for a real
recovery window is a slow test that people delete.
"""
from __future__ import annotations

import asyncio

import pytest

import ast
import pathlib

from app.core.circuit_breaker import CircuitBreaker, CircuitOpen

REPO = pathlib.Path(__file__).resolve().parents[2]
APP = REPO / "backend/app"

#: Outbound dependency calls that are NOT behind the shared breaker, and why. FS-846..848
#: asked for breakers on Postgres, Redis and Redpanda; this is what that resolved to after
#: reading each call path, because two of them turned out to be already-protected or
#: better-protected by something else.
NOT_BEHIND_THE_BREAKER = {
    "postgres": (
        "DELIBERATE. `pool_pre_ping` validates a connection before handing it out and "
        "`DB_POOL_TIMEOUT` (10s, FS-839) bounds the wait, so a dead database already "
        "fails fast without occupying a pool slot indefinitely. A breaker on the PRIMARY "
        "datastore also carries a risk the others do not: if its half-open logic is wrong "
        "the application stays down after the database has recovered, converting a "
        "database outage into an application outage that outlives it. The existing "
        "mechanisms answer the same question with less to get wrong."
    ),
    "redpanda:edge_ingest": (
        "ALREADY HAS ONE, hand-rolled: `_unavailable_until` plus `_retry_seconds` in "
        "`services/edge_ingest.py`, whose own comment says 'Trip the circuit'. It works "
        "and it is on the hottest path in the product, so replacing it with the shared "
        "class would be risk for no behavioural gain. Worth migrating only if that file "
        "is being changed for another reason."
    ),
    "redis:the_other_five_clients": (
        "THE REAL FINDING UNDER FS-846..848. There is no shared accessor for either "
        "dependency: six modules call `redis.from_url` and five construct their own "
        "`AIOKafkaProducer`, so there is no single seam to instrument and each site would "
        "have to be wrapped by hand. Introducing shared accessors is the right fix and is "
        "a refactor across eleven call sites in several lanes, which is a larger change "
        "than adding a breaker and should be its own."
    ),
}


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _fail():
    raise ConnectionError("dependency is down")


async def _ok():
    return "served"


class TestItOpensOnlyWhenTheDependencyIsReallyDown:
    @pytest.mark.asyncio
    async def test_it_stays_closed_below_the_threshold(self):
        breaker = CircuitBreaker("redis", failure_threshold=3, clock=_Clock())
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await breaker.call(_fail)
        assert breaker.state == "closed"

    @pytest.mark.asyncio
    async def test_one_success_resets_the_count(self):
        """CONSECUTIVE failures, not a rate. Intermittent errors must never trip it —
        otherwise the breaker becomes the outage on a merely flaky dependency."""
        breaker = CircuitBreaker("redis", failure_threshold=3, clock=_Clock())
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await breaker.call(_fail)
        await breaker.call(_ok)
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await breaker.call(_fail)
        assert breaker.state == "closed", "the success did not reset the failure count"

    @pytest.mark.asyncio
    async def test_it_opens_at_the_threshold(self):
        breaker = CircuitBreaker("redis", failure_threshold=3, clock=_Clock())
        for _ in range(3):
            with pytest.raises(ConnectionError):
                await breaker.call(_fail)
        assert breaker.state == "open"


class TestAnOpenBreakerCostsNothing:
    @pytest.mark.asyncio
    async def test_the_call_is_not_attempted(self):
        """THE ENTIRE POINT. If the call still happened, the caller would still pay the
        connect timeout and the breaker would be decoration."""
        clock = _Clock()
        breaker = CircuitBreaker("redis", failure_threshold=1, clock=clock)
        with pytest.raises(ConnectionError):
            await breaker.call(_fail)

        attempted = False

        async def _should_not_run():
            nonlocal attempted
            attempted = True

        with pytest.raises(CircuitOpen):
            await breaker.call(_should_not_run)
        assert not attempted, "the breaker was open and the call was made anyway"

    @pytest.mark.asyncio
    async def test_it_says_when_to_come_back(self):
        clock = _Clock()
        breaker = CircuitBreaker(
            "redis", failure_threshold=1, recovery_seconds=30, clock=clock
        )
        with pytest.raises(ConnectionError):
            await breaker.call(_fail)
        clock.advance(10)
        with pytest.raises(CircuitOpen) as excinfo:
            await breaker.call(_ok)
        assert 19 < excinfo.value.retry_in <= 20


class TestRecoveryIsOneTrialNotAStampede:
    @pytest.mark.asyncio
    async def test_a_successful_trial_closes_it(self):
        clock = _Clock()
        breaker = CircuitBreaker(
            "redis", failure_threshold=1, recovery_seconds=30, clock=clock
        )
        with pytest.raises(ConnectionError):
            await breaker.call(_fail)
        clock.advance(31)
        assert await breaker.call(_ok) == "served"
        assert breaker.state == "closed"

    @pytest.mark.asyncio
    async def test_a_failed_trial_reopens_immediately(self):
        """It must NOT count toward the threshold again: the dependency has just said it
        is still down, and there is nothing to accumulate."""
        clock = _Clock()
        breaker = CircuitBreaker(
            "redis", failure_threshold=5, recovery_seconds=30, clock=clock
        )
        for _ in range(5):
            with pytest.raises(ConnectionError):
                await breaker.call(_fail)
        clock.advance(31)
        with pytest.raises(ConnectionError):
            await breaker.call(_fail)
        assert breaker.state == "open"
        with pytest.raises(CircuitOpen):
            await breaker.call(_ok)

    @pytest.mark.asyncio
    async def test_only_one_caller_gets_the_trial(self):
        """A recovering dependency must not be hit by every waiting caller at once — that
        is how a breaker turns a recovering service back into a dead one."""
        clock = _Clock()
        breaker = CircuitBreaker(
            "redis", failure_threshold=1, recovery_seconds=30, clock=clock
        )
        with pytest.raises(ConnectionError):
            await breaker.call(_fail)
        clock.advance(31)

        attempts = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow():
            nonlocal attempts
            attempts += 1
            started.set()
            await release.wait()
            return "served"

        trial = asyncio.create_task(breaker.call(_slow))
        await asyncio.wait_for(started.wait(), timeout=2)

        for _ in range(4):
            with pytest.raises(CircuitOpen):
                await breaker.call(_slow)

        release.set()
        await trial
        assert attempts == 1, f"{attempts} callers reached the dependency, expected 1"


class TestTheBreakerDoesNotSerialiseTraffic:
    @pytest.mark.asyncio
    async def test_calls_run_concurrently_while_closed(self):
        """The lock covers the state decision, never the call. Holding it across the call
        would serialise every request through the dependency — a breaker meant to protect
        throughput becoming the thing that destroys it."""
        breaker = CircuitBreaker("redis", clock=_Clock())
        in_flight = 0
        peak = 0

        async def _concurrent():
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            in_flight -= 1
            return True

        await asyncio.gather(*(breaker.call(_concurrent) for _ in range(5)))
        assert peak == 5, f"only {peak} calls overlapped; the breaker is serialising"


class TestTheCoverageIsRecordedHonestly:
    """FS-846..848 asked for three breakers. Reading the call paths turned that into one
    primitive, two applications, and three recorded reasons — which is a better answer
    than three breakers applied uniformly, but only if the reasons are written down.
    """

    @pytest.mark.parametrize("dependency", sorted(NOT_BEHIND_THE_BREAKER))
    def test_every_exclusion_says_why(self, dependency):
        """An exemption without a reason is an exemption nobody will revisit."""
        assert len(NOT_BEHIND_THE_BREAKER[dependency]) > 120

    def test_the_paths_that_are_wrapped_actually_use_it(self):
        """A breaker constructed and never called is decoration. Asserted per module, so
        deleting the `.call(` leaves the attribute and still fails."""
        for module in ("services/feature_flags.py", "services/command_executor.py"):
            tree = ast.parse((APP / module).read_text())
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "call"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "_breaker"
            ]
            assert calls, (
                f"{module} constructs a CircuitBreaker but never calls through it, so "
                f"the dependency is still contacted on every request while it is down."
            )

    def test_the_edge_ingest_claim_is_still_true(self):
        """The register says edge_ingest has its own breaker and therefore does not need
        this one. If that mechanism is removed, the exemption becomes wrong and this path
        silently loses its protection."""
        source = (APP / "services/edge_ingest.py").read_text()
        assert "_unavailable_until" in source, (
            "edge_ingest no longer has its hand-rolled circuit breaker, so the register "
            "entry excusing it from the shared one is now false and that path pays the "
            "full broker timeout per reading."
        )

    def test_the_postgres_claim_is_still_true(self):
        """The register declines a Postgres breaker because pool_pre_ping and
        DB_POOL_TIMEOUT already fail fast. If either is removed the reasoning collapses."""
        source = (APP / "db/database.py").read_text()
        assert "pool_pre_ping" in source and "pool_timeout" in source, (
            "the Postgres exemption rests on pool_pre_ping and pool_timeout, and one of "
            "them is gone — so a dead database no longer fails fast and the decision not "
            "to add a breaker has to be revisited."
        )
