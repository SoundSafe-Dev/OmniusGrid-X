from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from jose import JWTError

import app.api.auth as auth_api
from app.core import sso
from app.core.security import (
    LocalTokenClaimsError,
    create_access_token,
    create_refresh_token,
    decode_local_token,
)
from app.core.session import SessionManager


def test_local_access_and_refresh_tokens_have_independent_required_claims():
    user_id = uuid4()
    access = decode_local_token(
        create_access_token({"sub": str(user_id)}),
        expected_type="access",
    )
    refresh_token = create_refresh_token({"sub": str(user_id)})
    refresh = decode_local_token(
        refresh_token,
        expected_type="refresh",
    )

    assert access["type"] == "access"
    assert refresh["type"] == "refresh"
    assert access["jti"] != refresh["jti"]
    assert datetime.fromtimestamp(access["iat"], tz=timezone.utc)
    assert datetime.fromtimestamp(refresh["exp"], tz=timezone.utc)
    with pytest.raises(LocalTokenClaimsError):
        decode_local_token(refresh_token, expected_type="access")


@pytest.mark.asyncio
async def test_keycloak_fallback_does_not_apply_local_jti_revocation(
    monkeypatch,
):
    keycloak_user = SimpleNamespace(is_active=True)
    authenticate_sso = AsyncMock(return_value=keycloak_user)
    local_revocation_check = AsyncMock(
        side_effect=AssertionError("Keycloak tokens do not use the local denylist")
    )

    monkeypatch.setattr(auth_api.settings, "KEYCLOAK_ENABLED", True)
    monkeypatch.setattr(
        auth_api,
        "decode_local_token",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(JWTError("not local")),
    )
    monkeypatch.setattr(sso, "authenticate_sso_token", authenticate_sso)
    monkeypatch.setattr(
        SessionManager,
        "is_token_revoked",
        local_revocation_check,
    )

    result = await auth_api.get_current_active_user(
        token="keycloak-token",
        header_token=None,
        db=object(),
    )

    assert result is keycloak_user
    authenticate_sso.assert_awaited_once()
    local_revocation_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_locally_signed_refresh_token_never_falls_back_to_keycloak(
    monkeypatch,
):
    authenticate_sso = AsyncMock()
    refresh_token = create_refresh_token({"sub": str(uuid4())})
    monkeypatch.setattr(auth_api.settings, "KEYCLOAK_ENABLED", True)
    monkeypatch.setattr(sso, "authenticate_sso_token", authenticate_sso)

    with pytest.raises(HTTPException) as exc:
        await auth_api.get_current_active_user(
            token=refresh_token,
            header_token=None,
            db=object(),
        )

    assert exc.value.status_code == 401
    authenticate_sso.assert_not_awaited()
