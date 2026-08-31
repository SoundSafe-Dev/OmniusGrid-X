"""A tenant's in-flight concurrency is capped, and a request has a deadline (FS-844/845).

**FS-844.** `Semaphore` returned zero hits across `backend/app`. FS-843 bounds a tenant's
requests per MINUTE, which does nothing about ten simultaneous slow ones: with
`DB_POOL_SIZE + DB_MAX_OVERFLOW = 10` per process (FS-839), one tenant issuing eleven
expensive queries holds every connection in that pod and every other tenant's request
queues on `DB_POOL_TIMEOUT` and then fails. Rate and concurrency are different resources
and only one of them was bounded.

**FS-845.** There was no server-level deadline at all. The ingress cuts the client off at
60s; nothing told the server, so the handler kept running — holding its connection and its
bulkhead slot — computing a response for a caller that had already disconnected. Under
load that is a pool leak whose worst case is the most expensive requests.

These are driven against a real ASGI app with real concurrency rather than asserted from
source, because the property that matters is what happens when requests overlap.
"""
from __future__ import annotations

import asyncio

import httpx
import jwt
import pytest
from fastapi import FastAPI

from app.core.config import settings
from app.middleware.bulkheads import (
    RequestDeadlineMiddleware,
    TenantBulkheadMiddleware,
    reset_bulkheads,
)


def _token(org: str) -> str:
    return jwt.encode({"sub": f"user-of-{org}", "org": org}, "k", algorithm="HS256")


def _app(*, slow: float = 0.0) -> FastAPI:
    app = FastAPI()

    @app.get("/work")
    async def work():
        if slow:
            await asyncio.sleep(slow)
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("handler exploded")

    app.add_middleware(TenantBulkheadMiddleware)
    app.add_middleware(RequestDeadlineMiddleware)
    return app


async def _get(app: FastAPI, path: str, org: str | None = None, n: int = 1):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        headers = {"Authorization": f"Bearer {_token(org)}"} if org else {}
        return await asyncio.gather(
            *(client.get(path, headers=headers) for _ in range(n))
        )


@pytest.fixture(autouse=True)
def _clean():
    reset_bulkheads()
    yield
    reset_bulkheads()


class TestTheBulkheadCapsOneTenant:
    @pytest.mark.asyncio
    async def test_requests_beyond_the_cap_are_refused_not_queued_forever(
        self, monkeypatch
    ):
        """THE DEFECT, DIRECTLY. Six concurrent requests from one tenant against a cap of
        two: two proceed, the rest are refused once the acquire timeout passes. Before
        this, all six would have proceeded and taken six of the pod's ten connections.
        """
        monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS_PER_TENANT", 2)
        monkeypatch.setattr(settings, "BULKHEAD_ACQUIRE_TIMEOUT_SECONDS", 0.15)

        responses = await _get(_app(slow=0.5), "/work", org="org-1", n=6)
        codes = [r.status_code for r in responses]

        assert codes.count(200) == 2, f"expected exactly the cap to pass: {codes}"
        assert codes.count(429) == 4, f"the rest must be refused: {codes}"

    @pytest.mark.asyncio
    async def test_the_refusal_says_retrying_is_worth_it(self, monkeypatch):
        """429 with Retry-After, not 503: unlike a quota, this resource frees itself as
        the tenant's own in-flight requests finish."""
        monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS_PER_TENANT", 1)
        monkeypatch.setattr(settings, "BULKHEAD_ACQUIRE_TIMEOUT_SECONDS", 0.1)

        responses = await _get(_app(slow=0.4), "/work", org="org-1", n=3)
        refused = [r for r in responses if r.status_code == 429]

        assert refused, "nothing was refused; the cap did not apply"
        assert "Retry-After" in refused[0].headers

    @pytest.mark.asyncio
    async def test_a_second_tenant_is_unaffected(self, monkeypatch):
        """THE WHOLE POINT OF A BULKHEAD. A cap that throttled everyone when one tenant
        was busy would be a global concurrency limit — it would spread one tenant's
        problem across the platform instead of containing it.
        """
        monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS_PER_TENANT", 1)
        monkeypatch.setattr(settings, "BULKHEAD_ACQUIRE_TIMEOUT_SECONDS", 0.4)
        app = _app(slow=0.2)

        noisy, quiet = await asyncio.gather(
            _get(app, "/work", org="noisy", n=3),
            _get(app, "/work", org="quiet", n=1),
        )

        assert quiet[0].status_code == 200, (
            "a quiet tenant was refused while another tenant was saturating its own "
            "bulkhead — the cap is global rather than per-tenant"
        )

    @pytest.mark.asyncio
    async def test_a_slot_is_released_when_the_handler_raises(self, monkeypatch):
        """A semaphore leaked on the error path fills permanently, and the first symptom
        is a tenant that can never make a request again after one 500."""
        monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS_PER_TENANT", 1)
        monkeypatch.setattr(settings, "BULKHEAD_ACQUIRE_TIMEOUT_SECONDS", 0.2)
        app = _app()

        await _get(app, "/boom", org="org-1", n=1)
        after = await _get(app, "/work", org="org-1", n=1)

        assert after[0].status_code == 200, (
            "the slot was not released when the handler raised, so the tenant is locked "
            "out after a single error"
        )

    @pytest.mark.asyncio
    async def test_zero_disables_it(self, monkeypatch):
        monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS_PER_TENANT", 0)
        responses = await _get(_app(slow=0.1), "/work", org="org-1", n=8)
        assert all(r.status_code == 200 for r in responses)


class TestTheDeadline:
    @pytest.mark.asyncio
    async def test_a_handler_past_the_deadline_is_cancelled(self, monkeypatch):
        """504, and — more importantly — the handler task is cancelled, which is what
        returns its database connection to the pool instead of leaving it held for work
        nobody is waiting for."""
        monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 0.1)
        monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS_PER_TENANT", 0)

        responses = await _get(_app(slow=2.0), "/work", org="org-1", n=1)
        assert responses[0].status_code == 504

    @pytest.mark.asyncio
    async def test_a_fast_handler_is_untouched(self, monkeypatch):
        monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 5.0)
        monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS_PER_TENANT", 0)
        responses = await _get(_app(slow=0.01), "/work", org="org-1", n=1)
        assert responses[0].status_code == 200

    @pytest.mark.asyncio
    async def test_zero_disables_it(self, monkeypatch):
        monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 0)
        monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS_PER_TENANT", 0)
        responses = await _get(_app(slow=0.2), "/work", org="org-1", n=1)
        assert responses[0].status_code == 200

    @pytest.mark.asyncio
    async def test_a_long_stream_is_not_killed(self, monkeypatch):
        """THE ONE THAT WOULD HAVE BROKEN SSE. `/rag/query/stream` holds a response open
        far longer than any request deadline. `call_next` returns once the handler has
        produced the response object — the body is streamed afterwards — so the deadline
        bounds time-to-first-byte and not the life of the stream. If that were wrong,
        this middleware would have silently truncated every streamed answer at 55s.
        """
        from fastapi.responses import StreamingResponse

        monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 0.2)
        monkeypatch.setattr(settings, "MAX_CONCURRENT_REQUESTS_PER_TENANT", 0)

        app = FastAPI()

        @app.get("/stream")
        async def stream():
            async def body():
                for i in range(4):
                    await asyncio.sleep(0.15)  # total 0.6s, well past the deadline
                    yield f"chunk-{i}\n".encode()

            return StreamingResponse(body(), media_type="text/event-stream")

        app.add_middleware(RequestDeadlineMiddleware)

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            response = await client.get("/stream")

        assert response.status_code == 200
        assert b"chunk-3" in response.content, (
            "the stream was truncated by the request deadline; SSE responses outlive it "
            "by design and must not be bounded by it"
        )
