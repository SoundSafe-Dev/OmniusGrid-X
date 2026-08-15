"""The error envelope must not drop headers the raiser attached.

`register_exception_handlers` wraps every StarletteHTTPException in the OmniusGrid
problem+json envelope. It rebuilt the response from the exception's status, detail
and trace id — and silently discarded ``exc.headers``.

Two of those headers are not decoration. RFC 9110 makes them mandatory, and a
spec-following client cannot act on the response without them:

  * §15.5.6 — a 405 response MUST generate an ``Allow`` header. Starlette's router
    already raises ``HTTPException(405, headers={"Allow": ...})``; the envelope threw
    it away, so every 405 the API has ever returned was malformed.
  * §11.6.1 — a 401 response MUST include ``WWW-Authenticate``. FastAPI's auth
    dependencies raise the challenge; the envelope threw that away too, so a client
    could not discover the scheme.

Found by the schemathesis contract suite (task 12), whose `unsupported_method` check
probes every operation with an undeclared method. It is one defect, but it failed on
every one of the 451 documented operations, because each gets a TRACE probe.
"""

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers


@pytest.fixture()
def client() -> TestClient:
    """A minimal app with the real handlers — not the whole application.

    The property under test belongs to register_exception_handlers, so building the
    smallest app that exercises it keeps this test from failing for reasons that have
    nothing to do with headers (missing DB, auth config, slow imports).
    """
    app = FastAPI()
    router = APIRouter()

    @router.get("/thing")
    async def _get_thing():
        return {"ok": True}

    @router.post("/needs-auth")
    async def _needs_auth():
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    app.include_router(router)
    register_exception_handlers(app)
    return TestClient(app)


def test_a_405_carries_the_allow_header(client: TestClient):
    response = client.post("/thing")

    assert response.status_code == 405
    assert response.headers.get("allow"), (
        "405 without an Allow header violates RFC 9110 §15.5.6 — the client cannot "
        "learn which methods the resource supports"
    )
    assert "GET" in response.headers["allow"]


def test_a_401_carries_the_authenticate_challenge(client: TestClient):
    response = client.post("/needs-auth")

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer", (
        "401 without WWW-Authenticate violates RFC 9110 §11.6.1 — the client cannot "
        "discover the authentication scheme to use"
    )


def test_the_envelope_body_is_still_intact(client: TestClient):
    """Propagating headers must not disturb the problem+json contract.

    Without this, the fix could pass its own tests by returning a bare Starlette
    response with the right headers and none of the envelope every client parses.
    """
    response = client.post("/thing")

    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 405
    assert body["error"]["code"] == "method_not_allowed"
    assert body["detail"]
    # trace_id is present as a member but stays None here: it is populated by the
    # request-id middleware, which this minimal app deliberately does not install.
    # Asserting it were truthy would test the middleware, not the envelope.
    assert "trace_id" in body["error"]
    assert body["instance"] == "/thing"


def test_an_error_with_no_headers_is_unaffected(client: TestClient):
    """The common case — most HTTPExceptions attach nothing — must not regress.

    `headers=None` has to stay absent rather than become an empty mapping, or every
    error response grows a header block that was never there.
    """
    response = client.get("/missing")

    assert response.status_code == 404
    assert "allow" not in response.headers
    assert response.json()["error"]["code"] == "not_found"


def _rate_limited_request(client):
    """A Starlette `Request` for the route the contract gate caught this on."""
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/register",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "app": client.app,
        }
    )


class _Limit:
    """The shape slowapi hands its handler. `str()` of it is the limit description."""

    error_message = None
    limit = "5 per 1 hour"

    def __str__(self) -> str:
        return self.limit


class TestTheRateLimiterUsesTheSameEnvelope:
    """429 was the one error shape a client could not handle generically (FS-727).

    Every error in this API is `application/problem+json` carrying `type`, `title`,
    `status`, `instance` and a trace id — that is what the OpenAPI document declares for
    429 on every route, and what the generated SDK is built to parse. The rate limiter
    answered plain JSON `{"detail": "..."}` from its own `JSONResponse`.

    **429 is the error most likely to be handled programmatically**, because the correct
    response to it is to back off and retry — so it is the worst one to make a special
    case. The contract gate found it as the single "Response violates schema" failure
    across 546 operations: `POST /auth/register` under a rate limit returned a body its own
    schema refuses.

    The headers matter for the same reason this file exists. `_envelope` REBUILDS the
    response, so `Retry-After` set on the old object afterwards would have been dropped —
    exactly how `Allow` and `WWW-Authenticate` were lost above. They are passed through the
    envelope instead.

    ASYNC TESTS, NOT `run_until_complete`. The first version drove the handler with
    `asyncio.get_event_loop().run_until_complete(...)` from a sync test. It passed alone and
    failed in the full suite, because by then another test had left that loop closed — a
    test whose result depends on what ran before it is not a test. pytest-asyncio is in auto
    mode here, so an `async def` gets its own loop.
    """

    async def test_the_body_is_the_problem_envelope(self, client: TestClient):
        import json

        from slowapi.errors import RateLimitExceeded

        from app.middleware.rate_limit import rate_limit_exceeded_handler

        response = await rate_limit_exceeded_handler(
            _rate_limited_request(client), RateLimitExceeded(_Limit())
        )

        assert response.media_type == "application/problem+json", (
            "the rate limiter answers plain JSON; every other error in this API is "
            "problem+json and the schema declares that for 429"
        )
        body = json.loads(bytes(response.body))
        for member in ("type", "title", "status", "instance"):
            assert member in body, f"the 429 envelope is missing {member!r}"
        assert body["status"] == 429

    async def test_the_retry_headers_survive_the_rebuild(self, client: TestClient):
        """`_envelope` builds a NEW response object. A header set on the old one is gone —
        which is the defect this whole file was written for."""
        from slowapi.errors import RateLimitExceeded

        from app.middleware.rate_limit import rate_limit_exceeded_handler

        response = await rate_limit_exceeded_handler(
            _rate_limited_request(client), RateLimitExceeded(_Limit())
        )
        assert response.headers.get("Retry-After") == "60", (
            "Retry-After was lost. A 429 without it tells a client to back off for an "
            "unknown period, which in practice means immediately."
        )
        assert response.headers.get("X-RateLimit-Limit")
