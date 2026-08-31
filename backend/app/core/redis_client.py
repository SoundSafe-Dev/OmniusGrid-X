"""One Redis accessor for the process (FS-847).

WHAT WAS HERE BEFORE. Seven modules each called `redis.from_url` and cached their own
client: the idempotency middleware, the health endpoint, feature flags, alarm rules, the
bulk processor, the export processor and the correlation job store. Each of those is a
**separate connection pool**, so a single API process opened up to seven pools against one
Redis — the same class of unmeasured resource use FS-839 found on the database side, where
nobody had chosen the number either.

It also meant there was no seam. FS-846..848 asked for a circuit breaker on Redis, and
there was nowhere to put one that would cover more than a single caller — which is why the
first pass could only wrap feature flags.

WHAT THIS DOES NOT DO. It does not change any caller's semantics. `decode_responses`
differs across callers on purpose (the idempotency middleware stores bytes, everything
else stores strings) and is part of the cache key rather than something to normalise —
handing a bytes caller a decoding client would corrupt its reads in a way that looks like
data loss.

THE BREAKER IS SHARED, deliberately. Redis is one dependency; one process should reach one
verdict about it. Seven independent breakers would each have to learn separately that it is
down, which is six unnecessary connect timeouts.
"""
from __future__ import annotations

from typing import Dict, Optional

import redis.asyncio as redis
import structlog
from redis.exceptions import RedisError

from app.core.circuit_breaker import CircuitBreaker
from app.services.transport_errors import TRANSPORT_ERRORS
from app.core.config import settings

logger = structlog.get_logger()

#: One client per (url, decode_responses). Keyed rather than singleton because both vary
#: legitimately, and a client is cheap while a POOL is not.
_clients: Dict[tuple[str, bool], redis.Redis] = {}

#: One verdict about Redis for the whole process. Exposed so callers that can degrade —
#: feature flags resolving to off, the rate limiter falling back to memory — can ask
#: before paying a timeout, and so `opsgrid_circuit_breaker_state{dependency="redis"}`
#: means the dependency rather than one of seven opinions about it.
breaker = CircuitBreaker("redis", failure_threshold=3)


def get_redis(
    *, url: Optional[str] = None, decode_responses: bool = True
) -> redis.Redis:
    """The shared client for this (url, decode_responses) pair.

    Lazily constructed and cached for the life of the process, which is what every caller
    was already doing individually — the difference is that they now share the pool.
    """
    key = (url or settings.REDIS_URL, decode_responses)
    client = _clients.get(key)
    if client is None:
        client = redis.from_url(key[0], decode_responses=key[1])
        _clients[key] = client
    return client


async def close_all() -> None:
    """Close every cached client. For shutdown and for tests."""
    for client in list(_clients.values()):
        try:
            await client.aclose()
        except (RedisError, *TRANSPORT_ERRORS):
            # NARROWED, not broad. Shutdown must not raise on a dependency that is
            # already unreachable — which is the common case, since we are often closing
            # because something is going away — but a TypeError here is a defect in this
            # module and should not be swallowed by a cleanup path.
            pass
    _clients.clear()


def reset_for_tests() -> None:
    """Drop the cache without closing, for tests that patch the URL."""
    _clients.clear()
