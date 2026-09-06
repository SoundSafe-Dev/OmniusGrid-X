"""Minimal SSO API (Task 6).

Does not expose the full keycloak_auth.py admin surface. Endpoints here are
safe entry points for the frontend SSO flow and status checks.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from typing import List, Optional

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.config import settings
from app.middleware.rate_limit import auth_rate_limit
from app.core.sso import (
    SSOValidationError,
    upsert_user_from_sso_claims,
    verify_keycloak_token,
)
from app.db.database import get_db
from app.db.models import User
from app.services.keycloak_service import _is_keycloak_configured

router = APIRouter()


class SSOCallbackRequest(BaseModel):
    access_token: str


class SSOStatus(BaseModel):
    """Unauthenticated: it tells a login page whether to offer the SSO button.

    Every field is derived from configuration and none is a secret — `issuer` and
    `client_id` are values the browser must know to start the flow, and both are `None`
    rather than empty strings when unset, so "not configured" is distinguishable from
    "configured with a blank".
    """

    enabled: bool
    configured: bool
    issuer: Optional[str] = None
    client_id: Optional[str] = None


class SSOUser(BaseModel):
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    #: `None` for a user not yet attached to an organization.
    organization_id: Optional[str] = None


class SSOMe(SSOUser):
    sso_enabled: bool


class SSOLoginResult(BaseModel):
    """The local user, plus the claims that decided the provisioning.

    `sso_roles` and `sso_groups` come off the verified Keycloak token, not the database —
    they are what the IdP asserted on this login, which is a different fact from the local
    `role` above and worth being able to compare.
    """

    user: SSOUser
    sso_roles: List[str]
    sso_groups: List[str]
    token_type: str


@router.get("/status", response_model=SSOStatus)
async def sso_status():
    """Report whether Keycloak SSO is enabled and minimally configured."""
    return {
        "enabled": settings.KEYCLOAK_ENABLED,
        "configured": _is_keycloak_configured(),
        "issuer": (
            f"{settings.KEYCLOAK_URL.rstrip('/')}/realms/{settings.KEYCLOAK_REALM}"
            if settings.KEYCLOAK_URL and settings.KEYCLOAK_REALM
            else None
        ),
        "client_id": settings.KEYCLOAK_CLIENT_ID or None,
    }


@router.get("/me", response_model=SSOMe)
async def sso_me(current_user: User = Depends(get_current_active_user)):
    """Current user profile (works with local JWT, dev-token, or Keycloak bearer)."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "organization_id": (
            str(current_user.organization_id) if current_user.organization_id else None
        ),
        "sso_enabled": settings.KEYCLOAK_ENABLED,
    }


@router.post("/login/callback", response_model=SSOLoginResult)
@auth_rate_limit(settings.AUTH_SSO_CALLBACK_RATE_LIMIT)
async def sso_login_callback(
    request: Request,
    payload: SSOCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Accept a Keycloak access token from the frontend, verify, and provision locally.

    Returns the local user record. The client should continue sending the Keycloak
    access token as the Bearer token on subsequent API calls.
    """
    if not _is_keycloak_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Keycloak SSO is not enabled or not configured",
        )

    # Verify the token once, then provision/update the local user from its claims.
    try:
        claims = await verify_keycloak_token(payload.access_token)
        user = await upsert_user_from_sso_claims(claims, db)
    except SSOValidationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or unprovisioned SSO token",
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "organization_id": str(user.organization_id) if user.organization_id else None,
        },
        "sso_roles": claims.roles,
        "sso_groups": claims.groups,
        "token_type": "bearer",
    }
