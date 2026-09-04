"""cached_aggregate: bounded caching that fails open, not silently stale forever (FS-896).

WHAT THIS BUYS. `Dashboard.tsx` polls `/overview` and `/fleet/oee` every 30s per open
tab; a short TTL cache collapses however many tabs one organisation has open onto one DB
round trip per cache lifetime, without needing every mutation path that could change the
answer to remember to invalidate it.

WHAT COULD GO WRONG, and what each test below pins:
  * A Redis outage must not break the route -- fail open to a direct compute.
  * A cached value must come back byte-identical (not accidentally coerced/reordered).
  * The TTL must actually be set, or a "bounded" cache is unbounded.
  * A corrupt value under our own key must not raise past the caller.
"""
from __future__ import annotations

import json

import fakeredis.aioredis as fakeredis
import pytest

from app.core import aggregate_cache
from app.core.aggregate_cache import cached_aggregate
from app.core.circuit_breaker import CircuitBreaker


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    """A fresh in-memory Redis and a closed (i.e. healthy) breaker per test."""
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(aggregate_cache.redis_client, "get_redis", lambda: client)
    monkeypatch.setattr(aggregate_cache.redis_client, "breaker", CircuitBreaker("test-redis"))
    return client


class TestACacheHitSkipsCompute:
    @pytest.mark.asyncio
    async def test_second_call_within_ttl_does_not_recompute(self):
        calls = {"n": 0}

        async def compute():
            calls["n"] += 1
            return {"total_assets": 7}

        first = await cached_aggregate("k1", compute)
        second = await cached_aggregate("k1", compute)

        assert first == second == {"total_assets": 7}
        assert calls["n"] == 1, "the second call recomputed instead of hitting the cache"

    @pytest.mark.asyncio
    async def test_different_keys_do_not_share_a_cache_entry(self):
        async def compute_a():
            return {"v": "a"}

        async def compute_b():
            return {"v": "b"}

        assert await cached_aggregate("org-a", compute_a) == {"v": "a"}
        assert await cached_aggregate("org-b", compute_b) == {"v": "b"}


class TestTheCacheIsActuallyBounded:
    @pytest.mark.asyncio
    async def test_the_stored_value_carries_a_ttl(self, _fake_redis):
        async def compute():
            return {"total_assets": 1}

        await cached_aggregate("k2", compute)

        ttl = await _fake_redis.ttl(f"{aggregate_cache._KEY_PREFIX}k2")
        assert 0 < ttl <= aggregate_cache.AGGREGATE_CACHE_TTL_SECONDS, (
            f"cached value has no expiry (ttl={ttl}) -- an unbounded cache never "
            f"reflects a change made after it was written"
        )

    @pytest.mark.asyncio
    async def test_ttl_is_well_under_the_poll_interval(self):
        """Dashboard.tsx polls every 30s; a cache that outlives a poll cycle would show
        one full cycle behind on every single refresh, not just occasionally."""
        assert aggregate_cache.AGGREGATE_CACHE_TTL_SECONDS < 30


class TestItFailsOpenRatherThanBreakingTheRoute:
    @pytest.mark.asyncio
    async def test_a_redis_read_failure_still_returns_the_computed_value(self, monkeypatch):
        async def _boom():
            raise ConnectionError("redis unreachable")

        monkeypatch.setattr(
            aggregate_cache.redis_client.breaker, "call", lambda fn: _boom()
        )

        async def compute():
            return {"total_assets": 42}

        result = await cached_aggregate("k3", compute)
        assert result == {"total_assets": 42}, (
            "a Redis failure on the read path broke the route instead of computing "
            "the answer directly"
        )

    @pytest.mark.asyncio
    async def test_a_corrupt_cached_value_is_treated_as_a_miss(self, _fake_redis):
        await _fake_redis.set(f"{aggregate_cache._KEY_PREFIX}k4", "not valid json{{{")

        async def compute():
            return {"total_assets": 9}

        result = await cached_aggregate("k4", compute)
        assert result == {"total_assets": 9}, (
            "a corrupt value under this cache's own key raised past the caller instead "
            "of being treated as a miss"
        )
