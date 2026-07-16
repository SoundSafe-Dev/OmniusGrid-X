"""Security utilities for local JWT authentication."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from jose import JWTError, jwt
from sqlalchemy import select

from app.core.config import settings
from app.core.session import SessionManager
from app.db.database import AsyncSessionLocal
from app.db.models import User


class LocalTokenClaimsError(ValueError):
    """A locally signed token is missing or has invalid required claims."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _create_token(
    data: dict,
    *,
    token_type: str,
    expires_delta: timedelta,
) -> str:
    now = _utcnow()
    payload = data.copy()
    payload.update(
        {
            "type": token_type,
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + expires_delta,
        }
    )
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Mint an independently identifiable local access token."""
    return _create_token(
        data,
        token_type="access",
        expires_delta=expires_delta
        or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Mint an independently identifiable local refresh token."""
    return _create_token(
        data,
        token_type="refresh",
        expires_delta=expires_delta
        or timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_local_token(token: str, *, expected_type: Optional[str] = None) -> dict:
    """Verify a local token and enforce its required session claims."""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )

    subject = payload.get("sub")
    jti = payload.get("jti")
    token_type = payload.get("type")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")

    try:
        UUID(str(subject))
        UUID(str(jti))
    except (TypeError, ValueError, AttributeError) as exc:
        raise LocalTokenClaimsError("invalid subject or jti") from exc

    if token_type not in {"access", "refresh"}:
        raise LocalTokenClaimsError("invalid token type")
    if expected_type is not None and token_type != expected_type:
        raise LocalTokenClaimsError("unexpected token type")
    if not isinstance(issued_at, (int, float)) or not isinstance(
        expires_at, (int, float)
    ):
        raise LocalTokenClaimsError("missing token timestamps")
    if issued_at > _utcnow().timestamp() + 60:
        raise LocalTokenClaimsError("token issued in the future")

    return payload


def token_expiry(payload: dict) -> datetime:
    """Return a decoded token's expiry as an aware UTC datetime."""
    try:
        return datetime.fromtimestamp(float(payload["exp"]), tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise LocalTokenClaimsError("invalid token expiry") from exc


async def get_current_user_ws(token: str) -> Optional[User]:
    """Validate an access JWT from a WebSocket connection."""
    if not token:
        return None

    try:
        payload = decode_local_token(token, expected_type="access")
        user_id = UUID(payload["sub"])
        async with AsyncSessionLocal() as db:
            if await SessionManager.is_token_revoked(payload["jti"], db):
                return None
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            return user if user and user.is_active else None
    except (JWTError, LocalTokenClaimsError, ValueError):
        return None
    except Exception:
        return None


async def verify_token(
    token: str,
    *,
    expected_type: Optional[str] = None,
) -> Optional[dict]:
    """Verify a local token and return its claims without fetching a user."""
    try:
        return decode_local_token(token, expected_type=expected_type)
    except (JWTError, LocalTokenClaimsError):
        return None
