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
