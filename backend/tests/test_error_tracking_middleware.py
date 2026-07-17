"""Unit tests for the error-tracking middleware (bare Starlette, no DB).

Asserts the load-bearing invariants: unhandled exceptions are recorded AND
re-raised unchanged, handled responses are ignored, a disabled tracker is a
pure passthrough, and a bug inside the tracker can never alter the response.
"""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.services import error_tracker as et
from app.middleware.error_tracking import ErrorTrackingMiddleware


@pytest.fixture
def app_factory(monkeypatch):
    """Build a TestClient over a fresh tracker with the given enabled flag."""
    def _make(enabled: bool):
        tracker = et.ErrorTracker()
        tracker.enabled = enabled
        # Point the middleware's imported singleton at our fresh instance.
        monkeypatch.setattr("app.middleware.error_tracking.error_tracker", tracker)

        async def ok(request):
            return PlainTextResponse("ok")

        async def not_found(request):
            return PlainTextResponse("nope", status_code=404)

        async def boom(request):
            raise ValueError("kaboom")

        app = Starlette(routes=[
            Route("/ok", ok),
            Route("/nf", not_found),
            Route("/boom", boom),
            Route("/items/{item_id}", boom),
        ])
        app.add_middleware(ErrorTrackingMiddleware)
        return TestClient(app, raise_server_exceptions=False), tracker
    return _make


def test_unhandled_exception_recorded_and_reraised(app_factory):
    client, tracker = app_factory(True)
    resp = client.get("/boom")
    assert resp.status_code == 500  # re-raised unchanged
    assert len(tracker._pending) == 1
    pending = next(iter(tracker._pending.values()))
    assert pending.exception_type == "ValueError"
    assert pending.count == 1


def test_success_and_handled_4xx_not_recorded(app_factory):
    client, tracker = app_factory(True)
    assert client.get("/ok").status_code == 200
    assert client.get("/nf").status_code == 404
    assert len(tracker._pending) == 0


def test_disabled_is_passthrough(app_factory):
    client, tracker = app_factory(False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    assert len(tracker._pending) == 0  # nothing recorded when disabled


def test_route_template_collapses_path_params(app_factory):
    client, tracker = app_factory(True)
    client.get("/items/1")
    client.get("/items/2")
    # Both concrete paths share the route template -> a single fingerprint.
    assert len(tracker._pending) == 1
    pending = next(iter(tracker._pending.values()))
    assert pending.route == "/items/{item_id}"
    assert pending.count == 2


def test_tracker_bug_never_breaks_response(app_factory, monkeypatch):
    client, tracker = app_factory(True)

    async def explode(*a, **k):
        raise RuntimeError("tracker is broken")

    monkeypatch.setattr(tracker, "record", explode)
    # The original 500 must still surface; the tracker bug is swallowed.
    resp = client.get("/boom")
    assert resp.status_code == 500
