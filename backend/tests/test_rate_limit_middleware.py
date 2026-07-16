import asyncio

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from slowapi.errors import RateLimitExceeded

from app.middleware.rate_limit import (
    auth_limiter,
    auth_rate_limit,
    get_auth_client_key,
    get_user_id_from_request,
    limiter,
    rate_limit,
    rate_limit_exceeded_handler,
)

_LIMITED_APP: FastAPI | None = None
_AUTH_LIMITED_APP: FastAPI | None = None


@pytest.fixture
def in_memory_limiter():
    old_enabled = limiter.enabled
    old_storage = limiter._storage
    old_limiter = limiter._limiter

    storage = MemoryStorage()
    limiter._storage = storage
    limiter._limiter = FixedWindowRateLimiter(storage)
    limiter.enabled = True
    limiter.reset()
    try:
        yield limiter
    finally:
        limiter.reset()
        limiter.enabled = old_enabled
        limiter._storage = old_storage
        limiter._limiter = old_limiter


@pytest.fixture
def in_memory_auth_limiter():
    old_enabled = auth_limiter.enabled
    old_storage = auth_limiter._storage
    old_limiter = auth_limiter._limiter

    storage = MemoryStorage()
    auth_limiter._storage = storage
    auth_limiter._limiter = FixedWindowRateLimiter(storage)
    auth_limiter.enabled = True
    auth_limiter.reset()
    try:
        yield auth_limiter
    finally:
        auth_limiter.reset()
        auth_limiter.enabled = old_enabled
        auth_limiter._storage = old_storage
        auth_limiter._limiter = old_limiter


def _limited_app() -> FastAPI:
    global _LIMITED_APP
    if _LIMITED_APP is not None:
        return _LIMITED_APP

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.get("/limited")
    @rate_limit("2/second")
    async def limited(request: Request):
        return {"key": get_user_id_from_request(request)}

    _LIMITED_APP = app
    return app


def _auth_limited_app() -> FastAPI:
    global _AUTH_LIMITED_APP
    if _AUTH_LIMITED_APP is not None:
        return _AUTH_LIMITED_APP

    app = FastAPI()
    app.state.auth_limiter = auth_limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    @app.post("/auth-limited")
    @auth_rate_limit("2/second")
    async def auth_limited(request: Request):
        return {"key": get_auth_client_key(request)}

    _AUTH_LIMITED_APP = app
    return app


@pytest.mark.asyncio
async def test_rate_limit_returns_429_after_repeated_requests(in_memory_limiter):
    app = _limited_app()
    transport = ASGITransport(app=app, client=("203.0.113.10", 1234))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [await client.get("/limited") for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert "Rate limit exceeded" in responses[2].json()["detail"]
    assert responses[2].headers["Retry-After"] == "60"
    assert "X-RateLimit-Limit" in responses[2].headers


@pytest.mark.asyncio
async def test_rate_limit_window_reset_allows_later_request(in_memory_limiter):
    app = _limited_app()
    transport = ASGITransport(app=app, client=("203.0.113.11", 1234))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/limited")).status_code == 200
        assert (await client.get("/limited")).status_code == 200
        assert (await client.get("/limited")).status_code == 429
        await asyncio.sleep(1.1)
        assert (await client.get("/limited")).status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_keys_authenticated_users_separately_on_same_ip(
    in_memory_limiter,
):
    app = _limited_app()
    transport = ASGITransport(app=app, client=("203.0.113.12", 1234))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user_a_headers = {"Authorization": "Bearer user-a-token"}
        user_b_headers = {"Authorization": "Bearer user-b-token"}

        assert (await client.get("/limited", headers=user_a_headers)).status_code == 200
        assert (await client.get("/limited", headers=user_a_headers)).status_code == 200
        assert (await client.get("/limited", headers=user_a_headers)).status_code == 429

        user_b_response = await client.get("/limited", headers=user_b_headers)

    assert user_b_response.status_code == 200
    assert user_b_response.json()["key"] == "user:user-b-token"


@pytest.mark.asyncio
async def test_rate_limit_falls_back_to_client_ip_for_anonymous_requests(
    in_memory_limiter,
):
    app = _limited_app()
    transport = ASGITransport(app=app, client=("203.0.113.13", 1234))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/limited")

    assert response.status_code == 200
    assert response.json()["key"] == "ip:203.0.113.13"


@pytest.mark.asyncio
async def test_auth_limit_stays_active_when_global_limiter_is_disabled(
    in_memory_auth_limiter,
):
    old_global_enabled = limiter.enabled
    limiter.enabled = False
    try:
        transport = ASGITransport(
            app=_auth_limited_app(),
            client=("203.0.113.14", 1234),
        )
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            responses = [await client.post("/auth-limited") for _ in range(3)]
    finally:
        limiter.enabled = old_global_enabled

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[0].json()["key"] == "auth-ip:203.0.113.14"
