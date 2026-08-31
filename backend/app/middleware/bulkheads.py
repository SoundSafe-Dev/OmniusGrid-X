"""Per-tenant concurrency caps and a global request deadline (FS-844, FS-845).

These are the two request-scoped bounds this platform had none of, and they are the pair
that makes FS-839's connection sizing hold under an adversarial tenant.

**FS-844 — the bulkhead.** `Semaphore` returned zero hits across `backend/app`, so nothing
limited how many requests one organisation could have IN FLIGHT at once. FS-843 bounds
requests per minute, which does nothing about ten simultaneous slow ones: with
`DB_POOL_SIZE + DB_MAX_OVERFLOW = 10` per process, one tenant issuing eleven expensive
queries occupies every connection in that pod, and every other tenant's request then
queues on `DB_POOL_TIMEOUT` and fails. Rate and concurrency are different resources.

**FS-845 — the deadline.** There was no server-level timeout of any kind. The ingress cuts
the client off at 60 seconds (`proxy-read-timeout`), and nothing told the server: the
handler carried on, holding its database connection and its bulkhead slot, computing a
response for a caller who had already given up. Under load that is a pool leak with a
timer on it — the abandoned work is exactly the expensive work.

WHAT THESE ARE HONESTLY NOT. The semaphore is per-process, because `asyncio.Semaphore` is.
Across N replicas a tenant's real ceiling is N x the cap. That still bounds any one
tenant's share of any one pod's pool, which is the failure being prevented; a
cluster-global cap would need a distributed counter on the request path, and paying Redis
latency on every request to bound something the pool already bounds locally is the wrong
trade.
"""
from __future__ import annotations

import asyncio
import collections
from typing import Dict

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.errors import problem_response
from app.middleware.rate_limit import get_tenant_key_from_request

logger = structlog.get_logger()

#: One semaphore per tenant, created on first sight. A plain dict rather than a bounded
#: cache: the key space is the customer list, not user input, and evicting a semaphore
#: while requests hold it would silently raise the cap for exactly those requests.
_semaphores: Dict[str, asyncio.Semaphore] = {}

#: How many requests are waiting for a slot, per tenant. Exported for the saturation
#: alert — a bulkhead that is always full is a capacity signal, and one that is never full
#: is a setting nobody needs to tune.
_waiting: Dict[str, int] = collections.defaultdict(int)


def _semaphore_for(key: str) -> asyncio.Semaphore:
    semaphore = _semaphores.get(key)
    if semaphore is None:
        semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_REQUESTS_PER_TENANT)
        _semaphores[key] = semaphore
    return semaphore


def reset_bulkheads() -> None:
    """Drop all semaphores. For tests only — see the note on eviction above."""
    _semaphores.clear()
    _waiting.clear()


class TenantBulkheadMiddleware(BaseHTTPMiddleware):
    """Cap one tenant's in-flight requests so it cannot take the whole pool (FS-844)."""

    async def dispatch(self, request: Request, call_next):
        cap = settings.MAX_CONCURRENT_REQUESTS_PER_TENANT
        if cap <= 0:
            return await call_next(request)

        key = get_tenant_key_from_request(request)
        semaphore = _semaphore_for(key)

        _waiting[key] += 1
        try:
            await asyncio.wait_for(
                semaphore.acquire(),
                timeout=settings.BULKHEAD_ACQUIRE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # 429, not 503: retrying genuinely helps here — unlike a quota, the resource
            # frees itself as the tenant's own in-flight requests finish. Retry-After is
            # the acquire timeout because that is the timescale on which it clears.
            logger.warning(
                "tenant_bulkhead_full",
                tenant=key,
                cap=cap,
                waiting=_waiting[key],
                path=request.url.path,
            )
            return problem_response(
                request,
                status_code=429,
                code="tenant_concurrency_limit",
                message=(
                    f"This organization already has {cap} requests in flight on this "
                    f"instance. The limit exists so one tenant cannot exhaust the shared "
                    f"database connection pool. Retry shortly."
                ),
                headers={
                    "Retry-After": str(int(settings.BULKHEAD_ACQUIRE_TIMEOUT_SECONDS))
                },
            )
        finally:
            _waiting[key] -= 1

        try:
            return await call_next(request)
        finally:
            semaphore.release()


class RequestDeadlineMiddleware(BaseHTTPMiddleware):
    """Give up on a request the client has almost certainly abandoned (FS-845).

    STREAMING IS NOT AFFECTED, and that is the subtle part. `call_next` returns as soon as
    the handler has produced a response object; for a `StreamingResponse` the body is sent
    afterwards, outside this timeout. So the deadline bounds how long a handler may take
    to START responding, and an SSE stream that stays open for an hour is untouched —
    which is what `/rag/query/stream` needs.
    """

    async def dispatch(self, request: Request, call_next):
        deadline = settings.REQUEST_TIMEOUT_SECONDS
        if deadline <= 0:
            return await call_next(request)

        try:
            return await asyncio.wait_for(call_next(request), timeout=deadline)
        except asyncio.TimeoutError:
            # The handler task is cancelled by `wait_for`, which is the entire point:
            # cancellation unwinds it and returns its database connection to the pool
            # rather than leaving it held for work nobody is waiting for.
            logger.warning(
                "request_deadline_exceeded",
                path=request.url.path,
                method=request.method,
                deadline_seconds=deadline,
            )
            return problem_response(
                request,
                status_code=504,
                code="request_deadline_exceeded",
                message=(
                    f"The server gave up after {deadline:.0f} seconds. This deadline sits "
                    f"just below the ingress timeout so the server stops work whose "
                    f"caller has already disconnected."
                ),
            )
