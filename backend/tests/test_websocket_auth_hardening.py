"""resolve_websocket_user must apply the same checks as the REST/ws-core path.

The /ws endpoint authenticates via auth.resolve_websocket_user, which did a raw
jwt.decode with NO token-type check and NO revocation check — so a REFRESH token
or a REVOKED (logged-out) access token could open a socket, even though
core.security.get_current_user_ws rejects both. These lock in that the ws path
rejects them too.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import app.db.database as db_module
from app.api import auth
from app.core.security import create_access_token, create_refresh_token
from app.core.session import SessionManager


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Result:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user


class _FakeSession:
    """Minimal async session whose user lookup returns a fixed active user."""

    def __init__(self, user):
        self._user = user

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _Result(self._user)


def _patch(monkeypatch, *, user, revoked):
    monkeypatch.setattr(db_module, "AsyncSessionLocal", lambda: _FakeSession(user))
    monkeypatch.setattr(
        SessionManager, "is_token_revoked", AsyncMock(return_value=revoked)
    )


def test_refresh_token_cannot_open_a_socket(monkeypatch):
    uid = str(uuid4())
    user = SimpleNamespace(id=uid, is_active=True)
    _patch(monkeypatch, user=user, revoked=False)
    refresh = create_refresh_token({"sub": uid})
    assert run(auth.resolve_websocket_user(refresh)) is None


def test_revoked_access_token_cannot_open_a_socket(monkeypatch):
    uid = str(uuid4())
    user = SimpleNamespace(id=uid, is_active=True)
    _patch(monkeypatch, user=user, revoked=True)
    access = create_access_token({"sub": uid})
    assert run(auth.resolve_websocket_user(access)) is None


def test_valid_active_access_token_is_accepted(monkeypatch):
    uid = str(uuid4())
    user = SimpleNamespace(id=uid, is_active=True)
    _patch(monkeypatch, user=user, revoked=False)
    access = create_access_token({"sub": uid})
    assert run(auth.resolve_websocket_user(access)) is user
