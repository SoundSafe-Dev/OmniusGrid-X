"""An unhandled 500 must arrive at the browser AS a 500 (FS-378).

THE DEFECT, found by a page-by-page QA sweep on 2026-08-01. Starlette installs the catch-all
``@app.exception_handler(Exception)`` on ``ServerErrorMiddleware`` — the outermost layer of
the stack, outside ``CORSMiddleware``. Its response therefore never passes back through CORS
and leaves without ``Access-Control-Allow-Origin``. Measured on the running stack:

    200 /api/v1/assets/            -> access-control-allow-origin: *
    404 /api/v1/nope               -> access-control-allow-origin: *
    500 /api/v1/nlp/sessions/…     -> no CORS header at all

A browser does not show that as a 500. It refuses the response, and the frontend's axios
client reports ``Network Error`` with no status, no body and no trace id — which is how the
sweep first met it, as a CORS complaint on the ``/nlp`` page.

WHY IT MATTERS MORE THAN A MISSING HEADER. This repo ships error triage. The failures that
feature exists for are unhandled 500s, and those were precisely the ones reaching the client
stripped of the ``trace_id`` that makes them triageable. Handled errors were always fine
(``ExceptionMiddleware`` sits inside CORS), so the gap was invisible to any test that only
checked 4xx.

AND IT HID ITSELF FROM THE SWEEP THAT FOUND IT. The Playwright driver recorded failed
requests from ``page.on('response')``. A response the browser rejects for CORS never fires
that event — it surfaces as ``ERR_FAILED``. So the sweep's own "no 4xx/5xx anywhere" line was
not evidence of no 500s; the one 500 present was only visible in the console log.

The fix is `UnhandledExceptionMiddleware` (app/middleware/unhandled.py), registered inside
CORS so the real CORS implementation decorates the response rather than a hand-rolled copy
of its rules.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware as StarletteCORS

from app.core.errors import register_exception_handlers
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.unhandled import UnhandledExceptionMiddleware

ORIGIN = "http://localhost:3000"


def _app(*, with_fix: bool) -> FastAPI:
    """A minimal app wired the way `app/main.py` wires the real one.

    `with_fix=False` reproduces the original ordering, so the tests below can be shown to
    fail against it — a guard nobody has watched fail is a guard of unknown strength.
    """
    app = FastAPI()
    register_exception_handlers(app)
    if with_fix:
        app.add_middleware(UnhandledExceptionMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Outermost, as in `app/main.py`. It is what sets `request.state.request_id`, so
    # without it the trace id is legitimately absent and this fixture would be testing a
    # weaker claim than the real app makes.
    app.add_middleware(RequestContextMiddleware)

    @app.get("/boom")
    async def _boom():
        raise RuntimeError("something the handler did not expect")

    @app.get("/fine")
    async def _fine():
        return {"ok": True}

    return app


def _get(app: FastAPI, path: str):
    # raise_server_exceptions=False so the client behaves like a real HTTP peer and
    # returns the response rather than re-raising in the test process.
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.get(path, headers={"Origin": ORIGIN})


class TestTheFiveHundredIsReadableByABrowser:
    def test_it_carries_the_cors_header(self):
        response = _get(_app(with_fix=True), "/boom")
        assert response.status_code == 500
        assert response.headers.get("access-control-allow-origin") == ORIGIN, (
            "the 500 has no Access-Control-Allow-Origin, so a browser rejects it and the "
            "client reports an opaque network error instead of a server error"
        )

    def test_the_trace_id_survives(self):
        """The single most valuable field on the response, and the one the CORS rejection
        was destroying — without it a reported failure cannot be found in the logs."""
        response = _get(_app(with_fix=True), "/boom")
        body = response.json()
        assert body["error"]["code"] == "internal_error"
        assert body["error"]["trace_id"], "no trace id on the 500"

    def test_the_envelope_is_unchanged(self):
        """Moving where the response is produced must not change what it says."""
        response = _get(_app(with_fix=True), "/boom")
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.json()
        assert body["status"] == 500
        assert body["detail"] == "internal server error"
        assert "something the handler did not expect" not in response.text, (
            "the exception message leaked to the client"
        )


class TestTheGuardCanSeeTheDefect:
    """Mutation check, in-file: the same assertions against the original ordering.

    Without these, all this file proves is that the current code passes — it could pass
    just as well if `UnhandledExceptionMiddleware` did nothing at all.
    """

    def test_without_the_middleware_the_header_is_missing(self):
        response = _get(_app(with_fix=False), "/boom")
        assert response.status_code == 500
        assert response.headers.get("access-control-allow-origin") is None, (
            "the unfixed arrangement now sets the CORS header on a 500 — either Starlette "
            "changed where the catch-all handler is installed, or this reproduction no "
            "longer reproduces anything, and the tests above are proving nothing"
        )

    def test_a_successful_response_always_had_the_header(self):
        """Both arrangements agree here. Establishes that the difference above is about
        the 500 specifically and not about CORS being misconfigured in the fixture."""
        for with_fix in (True, False):
            response = _get(_app(with_fix=with_fix), "/fine")
            assert response.headers.get("access-control-allow-origin") == ORIGIN


class TestTheRealAppKeepsTheOrdering:
    """`add_middleware` inserts at index 0, so the LAST registered is the OUTERMOST.
    `UnhandledExceptionMiddleware` must therefore be registered BEFORE `CORSMiddleware`
    to sit inside it — an edit that swaps them restores the defect while leaving both
    lines present and plausible."""

    def test_the_middleware_is_installed(self):
        from app.main import app

        classes = [m.cls for m in app.user_middleware]
        assert UnhandledExceptionMiddleware in classes, (
            "UnhandledExceptionMiddleware is not installed on the real app"
        )

    def test_it_is_inside_cors(self):
        from app.main import app

        classes = [m.cls for m in app.user_middleware]
        cors = next(
            i for i, c in enumerate(classes) if c in (CORSMiddleware, StarletteCORS)
        )
        unhandled = classes.index(UnhandledExceptionMiddleware)
        # Higher index == added earlier == deeper in the stack.
        assert unhandled > cors, (
            "UnhandledExceptionMiddleware is registered OUTSIDE CORSMiddleware, so its 500 "
            "bypasses CORS exactly as the original defect did. Register it before "
            "add_middleware(CORSMiddleware) in app/main.py."
        )
