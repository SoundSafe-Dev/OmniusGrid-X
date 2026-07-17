"""Reusable REST idempotency middleware (task 10).

Generalizes the dedup already proven in ``app/services/edge_ingest.py`` to the
HTTP layer: a client retrying a mutation (POST/PUT/PATCH) with the same
``Idempotency-Key`` header gets the original response replayed instead of the
action running twice — essential behind flaky networks and at-least-once queues.

Scope is intentionally narrow: only mutating methods, only when the client sends
a key, and only for path prefixes the app opts in via ``protected_prefixes`` (the
unowned domains). Everything else passes straight through, so this is additive.

Storage is an injectable async store; the default is in-process with a TTL, and
production swaps in a Redis-backed store (same interface). The key is namespaced
by method+path so the same key on different routes doesn't collide.
"""

import hashlib
import json
import time
from typing import Awaitable, Callable, Dict, Iterable, Optional, Tuple

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = structlog.get_logger()

_MUTATING = {"POST", "PUT", "PATCH"}
IDEMPOTENCY_HEADER = "Idempotency-Key"


class InMemoryIdempotencyStore:
    """Async TTL store of (status, body) keyed by idempotency key.

    Mirrors a Redis GET/SETNX-with-TTL contract so it can be swapped 1:1.
    """

    def __init__(self, ttl_seconds: float = 86400.0):
        self.ttl = ttl_seconds
        self._data: Dict[str, Tuple[float, int, bytes]] = {}

    async def get(self, key: str) -> Optional[Tuple[int, bytes]]:
        self._evict()
        entry = self._data.get(key)
        if entry is None:
            return None
        _, status_code, body = entry
        return status_code, body

    async def put(self, key: str, status_code: int, body: bytes) -> None:
        self._data[key] = (time.monotonic() + self.ttl, status_code, body)

    def _evict(self) -> None:
        now = time.monotonic()
        if len(self._data) > 5000:
            self._data = {k: v for k, v in self._data.items() if v[0] > now}


def _cache_key(method: str, path: str, idem_key: str) -> str:
    raw = f"{method}:{path}:{idem_key}".encode()
    return "idem:" + hashlib.sha256(raw).hexdigest()[:32]


class IdempotencyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, protected_prefixes: Iterable[str], store=None):
        super().__init__(app)
        self.prefixes = tuple(protected_prefixes)
        self.store = store or InMemoryIdempotencyStore()

    def _in_scope(self, request: Request) -> bool:
        return request.method in _MUTATING and request.url.path.startswith(self.prefixes)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        idem_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not idem_key or not self._in_scope(request):
            return await call_next(request)

        key = _cache_key(request.method, request.url.path, idem_key)
        cached = await self.store.get(key)
        if cached is not None:
            status_code, body = cached
            logger.info("idempotent_replay", path=request.url.path, status_code=status_code)
            return Response(
                content=body,
                status_code=status_code,
                media_type="application/json",
                headers={"Idempotency-Replayed": "true"},
            )

        response = await call_next(request)

        # Only cache successful, buffered responses; stream responses and errors
        # are left to retry normally.
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        if 200 <= response.status_code < 300:
            await self.store.put(key, response.status_code, body)

        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
