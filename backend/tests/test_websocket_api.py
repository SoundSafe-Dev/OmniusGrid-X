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

from app.api import websocket as ws_module


@pytest.fixture
def client(monkeypatch):
    async def fake_auth(token):
        return types.SimpleNamespace(id=uuid.uuid4(), organization_id="org-1")

    monkeypatch.setattr(ws_module, "get_current_user_ws", fake_auth)
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
