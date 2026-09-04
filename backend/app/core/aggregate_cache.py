"""A bounded, explicitly-invalidated cache for polled tenant aggregates (FS-896).

WHY THIS EXISTS. Redis is used for eight things in this codebase and none of them is
caching — the only memoisation anywhere is `lru_cache` on singleton constructors
(`core/config.py` and six others), which caches an object for the life of the process, not
a value that changes. `Dashboard.tsx` polls `/overview` and `/fleet/oee` every 30 seconds
PER OPEN TAB (FS-879/880's own finding), so every tab a customer leaves open is another
full round of the aggregate queries, all asking the same organisation the same question
within the same half-minute.

BOUNDED, NOT INVALIDATED ON WRITE. A cache invalidated by writes needs every mutation
path that could change the answer to remember to clear it — miss one (a new alarm, an
asset state change written by a worker rather than a request) and the dashboard is wrong
forever, silently, which is a worse failure than being briefly stale. A short TTL bounds
the staleness instead: `AGGREGATE_CACHE_TTL_SECONDS` is deliberately well under the
30-second poll interval, so a cached answer is never more than one poll behind what a
fresh query would show, and every tenant's cache expires on its own without anything
having to remember to clear it.

FAILS OPEN. A Redis outage must not take the dashboard down with it — every read and
write here goes through the shared breaker (`core/redis_client.py`) and falls back to
computing the answer directly on any `CircuitOpen`/`RedisError`/`OSError`. Caching is an
optimisation; the aggregate itself is not allowed to depend on it.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import structlog
from redis.exceptions import RedisError

from app.core import redis_client
from app.core.circuit_breaker import CircuitOpen

logger = structlog.get_logger()

#: Well under the 30s poll interval both cached routes are polled at (Dashboard.tsx:159),
#: so a cached answer is never more than one poll cycle stale.
AGGREGATE_CACHE_TTL_SECONDS = 15

_KEY_PREFIX = "aggcache:"


async def cached_aggregate(
    cache_key: str,
    compute: Callable[[], Awaitable[dict[str, Any]]],
    *,
    ttl_seconds: int = AGGREGATE_CACHE_TTL_SECONDS,
) -> dict[str, Any]:
    """Return `compute()`'s result, serving a cached copy when one is fresh.

    `cache_key` must already identify the tenant and every parameter the answer varies
    on (org id, time range, ...) -- this function does not scope anything itself.
    """
    full_key = f"{_KEY_PREFIX}{cache_key}"
    try:
        cached = await redis_client.breaker.call(
            lambda: redis_client.get_redis().get(full_key)
        )
    except (CircuitOpen, RedisError, OSError) as exc:
        logger.debug("aggregate_cache_read_failed", key=cache_key, error=str(exc)[:120])
        cached = None

    if cached is not None:
        try:
            return json.loads(cached)
        except (TypeError, ValueError) as exc:
            # A corrupt or foreign value under our own prefix should never break the
            # route -- fall through and recompute as if it were a miss.
            logger.warning("aggregate_cache_corrupt_value", key=cache_key, error=str(exc))

    result = await compute()

    try:
        await redis_client.breaker.call(
            lambda: redis_client.get_redis().set(
                full_key, json.dumps(result), ex=ttl_seconds
            )
        )
    except (CircuitOpen, RedisError, OSError) as exc:
        logger.debug("aggregate_cache_write_failed", key=cache_key, error=str(exc)[:120])
    except (TypeError, ValueError) as exc:
        # A response containing something json.dumps cannot serialise (should not
        # happen for these two routes, both of which are plain dict/number data) must
        # still be returned to the caller -- only the caching step is skipped.
        logger.warning("aggregate_cache_not_serialisable", key=cache_key, error=str(exc))

    return result
