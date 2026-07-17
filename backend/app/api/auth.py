"""Authentication API routes."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from jwt import PyJWTError as JWTError
from passlib.context import CryptContext
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User, Organization
from app.models.schemas import Token, UserCreate
from app.core.config import settings
from app.core.security import (
    LocalTokenClaimsError,
    create_access_token,
    create_refresh_token,
    decode_local_token,
    token_expiry,
)
from app.core.session import SessionManager
from app.db.database import get_db
from app.db.models import Organization, User
from app.middleware.rate_limit import auth_rate_limit
from app.models.schemas import Token, UserCreate

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="api/v1/auth/login",
    auto_error=False,
)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _invalid_refresh_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
    )


def _request_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


async def get_token_from_header(
    authorization: Optional[str] = Header(None),
) -> Optional[str]:
    """Extract a bearer token without requiring OAuth2 validation."""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


async def _load_local_user(
    payload: dict,
    db: AsyncSession,
    *,
    check_revocation: bool,
) -> User:
    if check_revocation and await SessionManager.is_token_revoked(
        payload["jti"], db
    ):
        raise _credentials_exception()

    result = await db.execute(
        select(User).where(User.id == UUID(payload["sub"]))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise _credentials_exception()
    return user


def _set_audit_context(request: Optional[Request], user: User) -> None:
    """Expose the authenticated identity to the audit middleware (reads request.state)."""
    if request is not None:
        request.state.user_id = str(user.id)
        request.state.organization_id = (
            str(user.organization_id) if user.organization_id else None
        )


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticate a locally issued access token."""
    if not token:
        raise _credentials_exception()
    try:
        payload = decode_local_token(token, expected_type="access")
    except (JWTError, LocalTokenClaimsError, ValueError):
        raise _credentials_exception()
    return await _load_local_user(payload, db, check_revocation=True)


async def get_current_active_user(
    request: Request = None,
    token: Optional[str] = Depends(oauth2_scheme),
    header_token: Optional[str] = Depends(get_token_from_header),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticate a local access token, then fall back to configured SSO."""
    actual_token = token or header_token

    # Dev-token bypass stays gated on ALLOW_DEV_TOKEN (converged security control:
    # validate_settings hard-fails if it is left enabled in production).
    if actual_token == "dev-token" and settings.ALLOW_DEV_TOKEN:
        dev_org_id = UUID("00000000-0000-0000-0000-000000000001")
        dev_user_id = UUID("00000000-0000-0000-0000-000000000001")

        org_result = await db.execute(
            select(Organization).where(Organization.id == dev_org_id)
        )
        org = org_result.scalar_one_or_none()
        if org is None:
            import uuid as uuid_lib

            org = Organization(
                id=dev_org_id,
                name="Dev Organization",
                slug=f"dev-{uuid_lib.uuid4().hex[:8]}",
            )
            db.add(org)
            await db.commit()

        user_result = await db.execute(select(User).where(User.id == dev_user_id))
        user = user_result.scalar_one_or_none()
        if user is None:
            user = User(
                id=dev_user_id,
                email="admin@omniusgrid.com",
                full_name="Dev Admin",
                role="admin",
                is_active=True,
                organization_id=dev_org_id,
                hashed_password=(
                    "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/"
                    "LewY5GyYHqF5pXa9W"
                ),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        _set_audit_context(request, user)
        return user

    if not actual_token:
        raise _credentials_exception()

    current_user: Optional[User] = None
    try:
        payload = decode_local_token(actual_token, expected_type="access")
    except JWTError:
        if settings.KEYCLOAK_ENABLED:
            from app.core.sso import authenticate_sso_token

            current_user = await authenticate_sso_token(actual_token, db)
    except (LocalTokenClaimsError, ValueError):
        raise _credentials_exception()
    else:
        current_user = await _load_local_user(
            payload,
            db,
            check_revocation=True,
        )

    if current_user is None:
        raise _credentials_exception()
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    _set_audit_context(request, current_user)
    return current_user


@dataclass(frozen=True)
class LogoutContext:
    user: User
    token: str
    payload: dict


async def get_logout_context(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> LogoutContext:
    """Authenticate logout without rejecting an already revoked access JTI."""
    if not token:
        raise _credentials_exception()
    try:
        payload = decode_local_token(token, expected_type="access")
    except (JWTError, LocalTokenClaimsError, ValueError):
        raise _credentials_exception()
    user = await _load_local_user(payload, db, check_revocation=False)
    return LogoutContext(user=user, token=token, payload=payload)


def _create_token_pair(user: User) -> tuple[str, dict, str, dict]:
    refresh_token = create_refresh_token({"sub": str(user.id)})
    refresh_payload = decode_local_token(refresh_token, expected_type="refresh")
    access_token = create_access_token(
        {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "sid": refresh_payload["jti"],
        }
    )
    access_payload = decode_local_token(access_token, expected_type="access")
    return access_token, access_payload, refresh_token, refresh_payload


@router.post(
    "/login",
    response_model=Token,
    summary="Login with email and password",
    description=(
        "Authenticate user credentials and return a rotating access/refresh "
        "token pair."
    ),
)
@auth_rate_limit(settings.AUTH_LOGIN_RATE_LIMIT)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Login and create the authoritative refresh session."""
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, _, refresh_token, refresh_payload = _create_token_pair(user)
    await SessionManager.create_session(
        user_id=user.id,
        token=refresh_token,
        jti=refresh_payload["jti"],
        expires_at=token_expiry(refresh_payload),
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent"),
        db=db,
    )
    user.last_login = datetime.now(timezone.utc)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post(
    "/register",
    summary="Register a new user",
    description=(
        "Create a new user account. WARNING: this endpoint is for "
        "development only and should be disabled in production."
    ),
)
@auth_rate_limit(settings.AUTH_REGISTER_RATE_LIMIT)
async def register(
    request: Request,
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user (dev only - disable in production)"""
    if not settings.ALLOW_OPEN_REGISTRATION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Open registration is disabled; users are provisioned by an administrator.",
        )
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        organization_id=user_data.organization_id,
        role="operator",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"message": "User created successfully", "user_id": str(user.id)}


class RefreshRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    refresh_token: str = Field(alias="refreshToken")


@router.post(
    "/refresh",
    response_model=Token,
    summary="Rotate refresh token",
    description="Consume one refresh token and return a replacement token pair.",
)
@auth_rate_limit(settings.AUTH_REFRESH_RATE_LIMIT)
async def refresh_access_token(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Rotate a refresh token exactly once."""
    try:
        old_payload = decode_local_token(
            body.refresh_token,
            expected_type="refresh",
        )
        user_id = UUID(old_payload["sub"])
    except (JWTError, LocalTokenClaimsError, ValueError):
        raise _invalid_refresh_exception()

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise _invalid_refresh_exception()

    access_token, _, refresh_token, refresh_payload = _create_token_pair(user)
    try:
        replacement = await SessionManager.rotate_session(
            old_token=body.refresh_token,
            old_jti=old_payload["jti"],
            user_id=user.id,
            new_token=refresh_token,
            new_jti=refresh_payload["jti"],
            new_expires_at=token_expiry(refresh_payload),
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
            db=db,
        )
        if replacement is None:
            await db.rollback()
            raise _invalid_refresh_exception()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _invalid_refresh_exception()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


class LogoutRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    refresh_token: Optional[str] = Field(default=None, alias="refreshToken")


@router.post(
    "/logout",
    summary="Revoke current authentication session",
    description="Revoke the current access token and linked refresh session.",
)
@auth_rate_limit(settings.AUTH_LOGOUT_RATE_LIMIT)
async def logout(
    request: Request,
    body: Optional[LogoutRequest] = None,
    context: LogoutContext = Depends(get_logout_context),
    db: AsyncSession = Depends(get_db),
):
    """Durably revoke live credentials; repeated calls remain successful."""
    await SessionManager.revoke_token_jti(
        jti=context.payload["jti"],
        user_id=context.user.id,
        token_type="access",
        expires_at=token_expiry(context.payload),
        db=db,
        reason="logout",
    )

    refresh_revoked = False
    refresh_was_supplied = body is not None and body.refresh_token is not None
    if refresh_was_supplied:
        try:
            refresh_payload = decode_local_token(
                body.refresh_token,
                expected_type="refresh",
            )
            if UUID(refresh_payload["sub"]) == context.user.id:
                refresh_revoked = await SessionManager.revoke_refresh_token(
                    token=body.refresh_token,
                    jti=refresh_payload["jti"],
                    user_id=context.user.id,
                    db=db,
                    reason="logout",
                )
        except (JWTError, LocalTokenClaimsError, ValueError):
            pass
    if not refresh_revoked and context.payload.get("sid"):
        try:
            await SessionManager.revoke_session_by_jti(
                jti=context.payload["sid"],
                user_id=context.user.id,
                db=db,
                reason="logout",
            )
        except ValueError:
            pass

    await db.commit()
    return {"message": "Logged out"}


@router.get(
    "/me",
    summary="Get current user information",
    description="Retrieve the authenticated user's profile information.",
)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user),
):
    """Get current user information."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "organization_id": (
            str(current_user.organization_id)
            if current_user.organization_id
            else None
        ),
        "last_login": (
            current_user.last_login.isoformat() if current_user.last_login else None
        ),
    }


@router.get(
    "/users",
    summary="Get organization users",
    description="Retrieve users in the authenticated user's organization.",
)
async def get_organization_users(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all users in the organization for assignment."""
    if not current_user.organization_id:
        return {"items": [], "total": 0}

    result = await db.execute(
        select(User).where(User.organization_id == current_user.organization_id)
    )
    users = result.scalars().all()
    user_list = [
        {
            "id": str(user.id),
            "name": user.full_name,
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
            "isActive": user.is_active,
            "createdAt": user.created_at.isoformat() if user.created_at else None,
            "updatedAt": user.updated_at.isoformat() if user.updated_at else None,
        }
        for user in users
    ]

    return {
        "items": user_list,
        "total": len(user_list)
    }


# ---- WebSocket authentication (ported from HARSH-CONTRIBUTION during the
# converged-pre-main merge: its websocket.py imports this, but its auth.py was
# resolved keep-ours; self-contained version against our dev-token flow). ----

async def resolve_websocket_user(token: Optional[str]) -> Optional[User]:
    """Authenticate WebSocket clients (JWT or dev-token). Returns None if invalid."""
    from app.db.database import AsyncSessionLocal

    if not token:
        return None

    async with AsyncSessionLocal() as db:
        if token == "dev-token" and settings.ALLOW_DEV_TOKEN:
            # Same fixed dev identity as get_current_active_user's bypass.
            dev_user_id = "00000000-0000-0000-0000-000000000001"
            result = await db.execute(select(User).where(User.id == dev_user_id))
            user = result.scalar_one_or_none()
            if user is None:
                # First-ever call: reuse the REST bypass to create org+user.
                user = await get_current_active_user(token="dev-token", header_token=None, db=db)
            return user

        try:
            payload = jwt.decode(
                token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
            user_id = payload.get("sub")
            if user_id is None:
                return None
            exp = payload.get("exp")
            if exp and datetime.utcnow().timestamp() > exp:
                return None
        except JWTError:
            return None

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        return user if user and user.is_active else None


# The admin-console dependency was consolidated into the single canonical
# app.middleware.rbac.require_admin (one admin gate, one graph-walkable symbol).
