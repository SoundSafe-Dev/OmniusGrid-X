"""The machinery every connector inherits: token cache, rate limiter, breaker.

This is the highest-leverage code in the ERP subsystem — a defect here is a defect in
all eight connectors at once — and it was the least tested. These tests are the result
of going looking, and two of them encode defects that were live.

Everything here is hermetic and fast. Timing assertions use the BURST window (one
second) rather than the per-minute window, so correctness is proven without minute-long
tests.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPConnectorBase, ERPType


class _Recording(ERPConnectorBase):
    """A connector that records how often it authenticates and how long it takes."""

    def __init__(self, *args, auth_delay: float = 0.05, expires_in: float = 3600, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth_calls = 0
        self._auth_delay = auth_delay
        self._expires_in = expires_in

    async def authenticate(self) -> str:
        self.auth_calls += 1
        # A real token round trip is not instantaneous, and the bug only appears in
        # the window where one is in flight.
        await asyncio.sleep(self._auth_delay)
        self._set_token(f"tok-{self.auth_calls}", self._expires_in)
        return self._auth_token

    async def fetch_data(self, entity_type, filters=None, limit=None) -> List[Dict[str, Any]]:
        return []

    async def health_check(self) -> Dict[str, Any]:
        return {}


def _connector(*, rpm: int = 600, burst: int = 100, **kwargs) -> _Recording:
    return _Recording(
        ERPConfig(
            erp_type=ERPType.GENERIC,
            auth_type=AuthType.OAUTH2,
            base_url="https://erp.example.com",
            auth_config={},
            rate_limit={"requests_per_minute": rpm, "burst_limit": burst},
            circuit_breaker=kwargs.pop("circuit_breaker", None),
        ),
        "org-1",
        "int-1",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------


class TestTokenStampede:
    """MEASURED DEFECT: 20 concurrent callers produced 20 token round trips.

    `get_auth_token` checked the cache, found it empty, and called `authenticate()`
    with no serialisation — so every coroutine that arrived while a token was in
    flight started its own.

    Wasteful against SAP and Entra ID. ACTIVELY DESTRUCTIVE against Intuit, where
    every refresh rotates the refresh token and retires the previous one: N
    concurrent refreshes create N competing rotations, N-1 of which are thrown away,
    and the stored credential is left invalid. The integration then fails with
    `invalid_grant`, which reads as a revoked authorization rather than a race.
    """

    async def test_concurrent_callers_authenticate_once(self):
        connector = _connector()
        tokens = await asyncio.gather(*[connector.get_auth_token() for _ in range(20)])

        assert connector.auth_calls == 1, (
            f"{connector.auth_calls} concurrent authentications; against Intuit that "
            f"is {connector.auth_calls} competing refresh-token rotations"
        )
        assert len(set(tokens)) == 1, "callers received different tokens"

    async def test_waiters_get_the_token_the_winner_fetched(self):
        """A waiter must return the cached value, not re-authenticate after the lock
        frees — which would be the stampede again, merely serialised."""
        connector = _connector()
        await asyncio.gather(*[connector.get_auth_token() for _ in range(10)])
        assert connector.auth_calls == 1
        assert connector._auth_token == "tok-1"

    async def test_a_cached_token_is_reused_without_authenticating(self):
        connector = _connector()
        await connector.get_auth_token()
        for _ in range(5):
            await connector.get_auth_token()
        assert connector.auth_calls == 1

    async def test_an_expired_token_re_authenticates_exactly_once(self):
        """The stampede window reopens on every expiry, so this is not a cold-start
        edge case — it recurs for the life of the process."""
        connector = _connector(expires_in=0.1)
        await connector.get_auth_token()
        assert connector.auth_calls == 1

        await asyncio.sleep(0.15)
        await asyncio.gather(*[connector.get_auth_token() for _ in range(15)])
        assert connector.auth_calls == 2, (
            f"expiry caused {connector.auth_calls - 1} re-authentications, expected 1"
        )

    async def test_invalidate_token_forces_exactly_one_re_authentication(self):
        connector = _connector()
        await connector.get_auth_token()
        connector.invalidate_token()
        await asyncio.gather(*[connector.get_auth_token() for _ in range(10)])
        assert connector.auth_calls == 2

    async def test_a_failing_authenticate_does_not_deadlock_the_lock(self):
        """If the lock is not released on the error path, the connector is bricked
        for the life of the process — a far worse failure than the one being fixed."""

        class _Failing(_Recording):
            async def authenticate(self):
                self.auth_calls += 1
                raise RuntimeError("token endpoint down")

        connector = _Failing(
            ERPConfig(
                erp_type=ERPType.GENERIC,
                auth_type=AuthType.OAUTH2,
                base_url="https://erp.example.com",
                auth_config={},
                rate_limit={"requests_per_minute": 600, "burst_limit": 100},
            ),
            "org-1",
            "int-1",
        )

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await connector.get_auth_token()

        # Reached at all == the lock was released each time.
        assert connector.auth_calls == 3


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


async def _noop():
    return 1


class TestRateLimiterUnderConcurrency:
    """MEASURED DEFECT: 100 operations against a 10-per-minute limit completed in 60
    seconds — ten times the configured rate.

    Every waiting coroutine computed the same deadline from the same snapshot, slept
    in parallel, and then all proceeded at once. There was no lock and no re-check.
    A rate limiter that only works for sequential callers is decorative, and the
    component whose whole job is avoiding a vendor throttle was causing one.
    """

    async def test_the_burst_limit_actually_serialises_concurrent_callers(self):
        connector = _connector(rpm=600, burst=3)

        started = time.monotonic()
        await asyncio.gather(*[connector.execute_with_retry(_noop) for _ in range(12)])
        elapsed = time.monotonic() - started

        # 12 operations at 3 per second cannot finish in under ~3 seconds.
        assert elapsed >= 2.5, (
            f"12 operations at a burst limit of 3/sec finished in {elapsed:.2f}s — "
            f"the limiter let concurrent callers through in a stampede"
        )

    async def test_no_one_second_window_exceeds_the_burst_limit(self):
        """The direct statement of the property, independent of wall-clock timing."""
        burst = 3
        connector = _connector(rpm=600, burst=burst)
        await asyncio.gather(*[connector.execute_with_retry(_noop) for _ in range(12)])

        stamps = sorted(connector._request_timestamps)
        for i, start in enumerate(stamps):
            in_window = [t for t in stamps[i:] if t - start < 1.0]
            assert len(in_window) <= burst, (
                f"{len(in_window)} requests inside a 1s window with burst limit {burst}"
            )

    async def test_recorded_timestamps_are_not_stale(self):
        """THE SECOND DEFECT, and it compounded the first.

        `now` was captured BEFORE sleeping and appended AFTER, so a request that
        waited recorded itself as having happened when it first asked — already
        outside its own window. The limiter under-counted its own traffic.

        With the bug, every timestamp clusters at t0 regardless of how long the run
        took. So the spread of recorded timestamps must track elapsed time.
        """
        connector = _connector(rpm=600, burst=3)

        started = time.monotonic()
        await asyncio.gather(*[connector.execute_with_retry(_noop) for _ in range(12)])
        elapsed = time.monotonic() - started

        stamps = sorted(connector._request_timestamps)
        spread = stamps[-1] - stamps[0]
        assert spread >= elapsed * 0.5, (
            f"run took {elapsed:.2f}s but the recorded timestamps span only "
            f"{spread:.2f}s — waiters stamped themselves with a stale time"
        )

    async def test_requests_within_the_limit_are_not_delayed(self):
        """The limiter must not tax traffic that is inside the budget."""
        connector = _connector(rpm=600, burst=50)
        started = time.monotonic()
        await asyncio.gather(*[connector.execute_with_retry(_noop) for _ in range(20)])
        assert time.monotonic() - started < 1.0

    async def test_the_window_drops_expired_entries(self):
        connector = _connector(rpm=600, burst=100)
        connector._request_timestamps = [time.time() - 120 for _ in range(500)]
        await connector.execute_with_retry(_noop)
        assert len(connector._request_timestamps) == 1, (
            "entries older than the 60s window were not evicted"
        )


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    async def test_it_opens_after_the_threshold_and_blocks(self):
        connector = _connector(circuit_breaker={"failure_threshold": 3, "recovery_timeout": 60})
        connector.retry_config["max_retries"] = 0

        async def _boom():
            raise Exception("503 Service Unavailable")  # transient, so it counts

        for _ in range(3):
            with pytest.raises(Exception):
                await connector.execute_with_retry(_boom)

        assert connector.circuit_breaker.state == "open"

        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            await connector.execute_with_retry(_noop)

    async def test_it_half_opens_after_the_recovery_timeout(self):
        connector = _connector(circuit_breaker={"failure_threshold": 2, "recovery_timeout": 0.1})
        connector.retry_config["max_retries"] = 0

        async def _boom():
            raise Exception("503 Service Unavailable")

        for _ in range(2):
            with pytest.raises(Exception):
                await connector.execute_with_retry(_boom)
        assert connector.circuit_breaker.state == "open"

        await asyncio.sleep(0.15)
        assert await connector.execute_with_retry(_noop) == 1
        assert connector.circuit_breaker.state == "closed"

    async def test_a_permanent_auth_failure_does_not_trip_the_breaker(self):
        """Deliberate. A wrong credential is not a reason to stop talking to a
        healthy system — the breaker exists for an overloaded or failing service. A
        bad secret should surface as an auth error every time, not disappear behind
        an open breaker whose message names neither the credential nor the system."""
        connector = _connector(circuit_breaker={"failure_threshold": 2, "recovery_timeout": 60})
        connector.retry_config["max_retries"] = 0

        async def _bad_credential():
            raise Exception("401 Unauthorized")

        for _ in range(5):
            with pytest.raises(Exception, match="401"):
                await connector.execute_with_retry(_bad_credential)

        assert connector.circuit_breaker.state == "closed"
