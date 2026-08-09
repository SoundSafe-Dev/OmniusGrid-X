"""Focused test for the Task 3 WebSocket server protocol contract.

The reconnection/backoff logic itself lives in the frontend (and the repo has no
JS test runner), but the frontend depends on the server honouring this message
contract: ping->pong (heartbeat), subscribe->subscription_updated (subscription
restore), and an error frame for unknown types. This verifies the server side via
Starlette's TestClient WebSocket, stubbing only auth (no DB).
"""

import types
import uuid

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import websocket as ws_module


@pytest.fixture
def client(monkeypatch):
    async def fake_auth(token):
        return types.SimpleNamespace(id=uuid.uuid4(), organization_id="org-1")

    monkeypatch.setattr(ws_module, "resolve_websocket_user", fake_auth)
    app = FastAPI()
    app.include_router(ws_module.router)
    return TestClient(app)


def _connect(client):
    return client.websocket_connect("/ws?token=x&organization_id=org-1")


def test_ping_gets_pong_with_timestamp(client):
    with _connect(client) as ws:
        assert ws.receive_json()["type"] == "connection_established"
        ws.send_json({"type": "ping", "timestamp": 123})
        pong = ws.receive_json()
        assert pong["type"] == "pong"
        assert pong["timestamp"] == 123


def test_subscribe_is_acknowledged(client):
    with _connect(client) as ws:
        ws.receive_json()  # connection_established
        ws.send_json({"type": "subscribe", "asset_ids": ["a1"], "message_types": ["telemetry"]})
        ack = ws.receive_json()
        assert ack["type"] == "subscription_updated"
        assert ack["payload"]["asset_ids"] == ["a1"]


def test_unknown_type_returns_error(client):
    with _connect(client) as ws:
        ws.receive_json()  # connection_established
        ws.send_json({"type": "totally-unknown"})
        err = ws.receive_json()
        assert err["type"] == "error"


def test_missing_token_is_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws?organization_id=org-1"):
            pass
    assert exc_info.value.code == 1008


def test_cross_tenant_organization_is_rejected(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws?token=x&organization_id=org-2"):
            pass
    assert exc_info.value.code == 1008


# --- FS-108: correlation id on the WebSocket path ---------------------------
# The HTTP middleware binds request_id for every request; the WebSocket scope
# bypasses BaseHTTPMiddleware, so the endpoint must bind the id itself. These
# lock in (1) the shared header->id derivation and (2) that a connection binds
# it from the handshake and unbinds on close.
from app.middleware.request_context import correlation_id_from_headers  # noqa: E402


def test_correlation_id_prefers_explicit_request_id():
    from starlette.datastructures import Headers

    headers = Headers({"X-Request-ID": "req-abc", "traceparent": "00-" + "a" * 32 + "-b" * 8 + "-01"})
    assert correlation_id_from_headers(headers) == "req-abc"


def test_correlation_id_falls_back_to_traceparent_trace_id():
    from starlette.datastructures import Headers

    trace_id = "b" * 32
    headers = Headers({"traceparent": f"00-{trace_id}-{'c' * 16}-01"})
    assert correlation_id_from_headers(headers) == trace_id


def test_correlation_id_mints_when_absent():
    from starlette.datastructures import Headers

    got = correlation_id_from_headers(Headers({}))
    assert got and len(got) == 32  # uuid4().hex


def test_websocket_binds_and_unbinds_correlation_id(client, monkeypatch):
    import structlog

    bound: list = []
    unbound: list = []
    real_bind = structlog.contextvars.bind_contextvars
    real_unbind = structlog.contextvars.unbind_contextvars

    def rec_bind(**kw):
        if "request_id" in kw:
            bound.append(kw["request_id"])
        return real_bind(**kw)

    def rec_unbind(*keys):
        unbound.extend(keys)
        return real_unbind(*keys)

    monkeypatch.setattr(structlog.contextvars, "bind_contextvars", rec_bind)
    monkeypatch.setattr(structlog.contextvars, "unbind_contextvars", rec_unbind)

    with client.websocket_connect(
        "/ws?token=x&organization_id=org-1", headers={"X-Request-ID": "ws-trace-1"}
    ) as ws:
        assert ws.receive_json()["type"] == "connection_established"

    # The session bound the handshake id, and unbound request_id on close.
    assert "ws-trace-1" in bound
    assert "request_id" in unbound
