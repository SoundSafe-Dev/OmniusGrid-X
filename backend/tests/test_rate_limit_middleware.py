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

    # Real JWTs — keying is by the `sub` claim (the earlier version used plain
    # strings like "user-a-token", which only worked because their first 16
    # chars happened to differ under the old token[:16] key).
    import jwt
    token_a = jwt.encode({"sub": "user-a", "type": "access"}, "s", algorithm="HS256")
    token_b = jwt.encode({"sub": "user-b", "type": "access"}, "s", algorithm="HS256")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user_a_headers = {"Authorization": f"Bearer {token_a}"}
        user_b_headers = {"Authorization": f"Bearer {token_b}"}

        assert (await client.get("/limited", headers=user_a_headers)).status_code == 200
        assert (await client.get("/limited", headers=user_a_headers)).status_code == 200
        assert (await client.get("/limited", headers=user_a_headers)).status_code == 429

        user_b_response = await client.get("/limited", headers=user_b_headers)

    assert user_b_response.status_code == 200
    assert user_b_response.json()["key"] == "user:user-b"


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


def _bearer_request(token: str):
    """Minimal Request with an Authorization header for keying tests."""
    from starlette.requests import Request as StarletteRequest
    scope = {
        "type": "http", "method": "GET", "path": "/", "headers":
        [(b"authorization", f"Bearer {token}".encode())],
        "client": ("1.2.3.4", 0), "query_string": b"",
    }
    return StarletteRequest(scope)


def test_rate_limit_key_is_per_user_not_shared():
    """Two different users must get different rate-limit keys.

    The old key was `user:{token[:16]}` — for HS256 the first 16 chars are the
    base64 of the identical header, so every authenticated user collapsed into
    ONE shared bucket (one user could throttle everyone).
    """
    import jwt
    t1 = jwt.encode({"sub": "user-aaaaaaaa", "type": "access"}, "s", algorithm="HS256")
    t2 = jwt.encode({"sub": "user-bbbbbbbb", "type": "access"}, "s", algorithm="HS256")
    k1 = get_user_id_from_request(_bearer_request(t1))
    k2 = get_user_id_from_request(_bearer_request(t2))
    assert k1 != k2, f"distinct users share a rate-limit bucket: {k1} == {k2}"
    assert k1.startswith("user:") and "user-aaaaaaaa" in k1


def test_rate_limit_key_stable_across_a_users_tokens():
    """The same user's budget should travel with them (keyed by identity)."""
    import jwt
    a = jwt.encode({"sub": "user-x", "type": "access", "jti": "1"}, "s", algorithm="HS256")
    b = jwt.encode({"sub": "user-x", "type": "access", "jti": "2"}, "s", algorithm="HS256")
    assert get_user_id_from_request(_bearer_request(a)) == get_user_id_from_request(_bearer_request(b))


class TestTheKeyFallbackIsNarrowAndVisible:
    """FS-970. The outer catch here was `except Exception: pass`.

    FS-910 narrowed the INNER catch (around `jwt.decode`) and left this one, on the
    reasoning that it was defence in depth. That reasoning was half right: two specific
    things really can raise here, and neither of them is every exception. A bare
    `Exception` also swallowed the case that matters most -- extraction breaking for
    EVERY request, which silently converts a per-user rate limit into a per-IP one and
    looks exactly like normal operation from the outside.
    """

    def test_a_raw_high_byte_in_the_header_keys_normally(self):
        """PINS A DISPROVEN PREMISE, which is why it asserts the boring outcome.

        The first draft of FS-970 also caught `UnicodeError`, on the theory that a raw
        0xE9 in the Authorization header would survive Starlette's latin-1 decode as a
        lone surrogate and blow up `token.encode()` in the hash fallback. It does not:
        latin-1 maps every byte to U+0000-U+00FF, all encodable, so the header arrives as
        `'Bearer abcédef'` and hashes like any other unparseable token. The catch tuple
        was narrowed to match reality, and this test exists so nobody re-adds
        `UnicodeError` on the same reasoning without first making this fail."""
        from starlette.requests import Request as StarletteRequest

        scope = {
            "type": "http", "method": "GET", "path": "/",
            "headers": [(b"authorization", b"Bearer abc\xe9def")],
            "client": ("1.2.3.4", 0), "query_string": b"",
        }
        key = get_user_id_from_request(StarletteRequest(scope))
        assert key.startswith("user:"), (
            f"expected the per-token hash fallback, got {key!r}. If this is now 'ip:...', "
            "the encode path started raising after all and UnicodeError belongs back in "
            "the catch tuple -- with this docstring corrected to say so."
        )

    def test_a_non_request_object_falls_back_instead_of_raising(self):
        """The AttributeError half: handed something that is not a Request (a test
        double, a middleware ordering mistake), keying must degrade rather than explode."""
        class NotARequest:
            @property
            def headers(self):
                raise AttributeError("no headers here")

        # get_remote_address needs a real-ish object; the point is only that the
        # AttributeError from `.headers` is caught rather than propagating.
        import pytest
        with pytest.raises(AttributeError):
            # It reaches get_remote_address, which fails on its own for a different
            # reason -- proving the FIRST AttributeError was caught, not this one.
            get_user_id_from_request(NotARequest())

    def test_a_programming_error_is_no_longer_swallowed(self):
        """The point of narrowing. A TypeError -- the shape a rename or a signature
        change produces -- must now propagate instead of every user silently sharing an
        IP bucket while the logs say nothing."""
        import pytest

        class ExplodingHeaders:
            @property
            def headers(self):
                raise TypeError("this is a bug, not a malformed request")

        with pytest.raises(TypeError):
            get_user_id_from_request(ExplodingHeaders())
