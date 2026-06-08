"""Focused unit tests for the Task 2 profiling middleware.

Uses a bare Starlette app + TestClient (no Docker/DB). Asserts the behaviours
fixed in this batch: requests that raise are still recorded, timing headers are
attached on success, and DB query listeners are only registered when enabled.
"""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware import profiling
from app.middleware.profiling import HTTP_REQUESTS_TOTAL, ProfilingMiddleware


def _count(method, endpoint, status):
    return HTTP_REQUESTS_TOTAL.labels(method, endpoint, status)._value.get()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(profiling, "PROFILING_ENABLED", True)

    async def ok(request):
        return PlainTextResponse("ok")

    async def boom(request):
        raise ValueError("boom")

    app = Starlette(routes=[Route("/ok", ok), Route("/boom", boom)])
    app.add_middleware(ProfilingMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_success_recorded_with_timing_headers(client):
    before = _count("GET", "/ok", "200")
    resp = client.get("/ok")
    assert resp.status_code == 200
    assert resp.headers.get("X-Process-Time-Ms") is not None
    assert resp.headers.get("X-DB-Query-Count") is not None
    assert _count("GET", "/ok", "200") == before + 1


def test_request_that_raises_is_recorded_as_500(client):
    # Previously the metrics emission ran after the try/finally and was skipped
    # entirely when call_next raised; now it is recorded (as 500) and re-raised.
    before = _count("GET", "/boom", "500")
    resp = client.get("/boom")
    assert resp.status_code == 500
    assert _count("GET", "/boom", "500") == before + 1


def test_db_listeners_registered_only_when_enabled(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(profiling, "_register_query_listeners", lambda: calls.__setitem__("n", calls["n"] + 1))

    class DummyApp:
        def add_middleware(self, *a, **k):
            pass

    monkeypatch.setattr(profiling, "PROFILING_ENABLED", True)
    profiling.setup_profiling(DummyApp())
    assert calls["n"] == 1

    monkeypatch.setattr(profiling, "PROFILING_ENABLED", False)
    profiling.setup_profiling(DummyApp())
    assert calls["n"] == 1  # not registered again when disabled
