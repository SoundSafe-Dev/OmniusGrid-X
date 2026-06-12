"""SSO / OIDC core (Task 6).

Keycloak access-token verification and local user provisioning. SAML/LDAP/OAuth
IdPs are expected to federate through Keycloak; this module validates Keycloak-
issued JWTs only.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import structlog
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.services.keycloak_service import _is_keycloak_configured, get_keycloak_service

logger = structlog.get_logger()

# Local password login is disabled for SSO users: their stored password hash is a
# bcrypt hash of a fresh random secret that is discarded, so verify_password can
# never succeed. Generated lazily so importing this module has no bcrypt cost.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _disabled_login_hash() -> str:
    return _pwd_context.hash(secrets.token_urlsafe(32))

_APP_ROLES = frozenset({"admin", "operator", "viewer"})


class SSOValidationError(Exception):
    """Raised when a bearer token fails OIDC validation."""


@dataclass
class SSOClaims:
    """Normalized identity extracted from a verified Keycloak access token."""

    subject: str
    email: str
    full_name: str
    enabled: bool
    email_verified: bool
    groups: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    organization_id: Optional[str] = None


def _keycloak_issuer() -> str:
    base = settings.KEYCLOAK_URL.rstrip("/")
    return f"{base}/realms/{settings.KEYCLOAK_REALM}"


def _collect_roles_and_groups(decoded: dict[str, Any]) -> tuple[list[str], list[str]]:
    roles: set[str] = set()
    groups: list[str] = []

    realm_access = decoded.get("realm_access") or {}
    for role in realm_access.get("roles") or []:
        roles.add(str(role))

    resource_access = decoded.get("resource_access") or {}
    client_access = resource_access.get(settings.KEYCLOAK_CLIENT_ID) or {}
    for role in client_access.get("roles") or []:
        roles.add(str(role))

    for group in decoded.get("groups") or []:
        groups.append(str(group))

    return sorted(roles), groups


def _normalize_claims(decoded: dict[str, Any]) -> SSOClaims:
    email = decoded.get("email") or decoded.get("preferred_username")
    if not email:
        raise SSOValidationError("Token missing email claim")

    given = decoded.get("given_name") or ""
    family = decoded.get("family_name") or ""
    full_name = decoded.get("name") or f"{given} {family}".strip() or email

    roles, groups = _collect_roles_and_groups(decoded)
    org_id = decoded.get("organization_id")
    if isinstance(org_id, list):
        org_id = org_id[0] if org_id else None

    return SSOClaims(
        subject=str(decoded.get("sub", "")),
        email=str(email).lower(),
        full_name=full_name,
        enabled=bool(decoded.get("enabled", True)),
        # Absent claim => treat as verified (the IdP already authenticated the
        # user); only an explicit `false` blocks login.
        email_verified=bool(decoded.get("email_verified", True)),
        groups=groups,
        roles=roles,
        organization_id=str(org_id) if org_id else None,
    )


def _validate_audience(decoded: dict[str, Any]) -> None:
    """Ensure the token was issued for this client."""
    client_id = settings.KEYCLOAK_CLIENT_ID
    azp = decoded.get("azp")
    aud = decoded.get("aud")
    if azp == client_id:
        return
    if isinstance(aud, str) and aud == client_id:
        return
    if isinstance(aud, list) and client_id in aud:
        return
    raise SSOValidationError("Token audience does not match configured client")


def _decode_keycloak_token_sync(token: str) -> dict[str, Any]:
    """Verify and decode a Keycloak JWT (sync — run in a thread)."""
    service = get_keycloak_service()
    options = {
        "verify_signature": True,
        "verify_aud": False,  # Keycloak uses azp; validated separately below.
        "verify_exp": True,
        "verify_iss": True,
    }
    try:
        decoded = service.keycloak_openid.decode_token(
            token,
            validate=True,
            options=options,
        )
    except Exception as exc:
        raise SSOValidationError(f"Keycloak token decode failed: {exc}") from exc

    issuer = decoded.get("iss")
    expected_issuer = _keycloak_issuer()
    if issuer != expected_issuer:
        raise SSOValidationError(f"Unexpected issuer: {issuer}")

    _validate_audience(decoded)
    return decoded


async def verify_keycloak_token(token: str) -> SSOClaims:
    """Verify a Keycloak access token and return normalized claims."""
    if not _is_keycloak_configured():
        raise SSOValidationError("Keycloak SSO is not enabled or configured")

    decoded = await asyncio.to_thread(_decode_keycloak_token_sync, token)
    claims = _normalize_claims(decoded)

    if not claims.enabled:
        raise SSOValidationError("Keycloak account is disabled")
    if not claims.email_verified:
        raise SSOValidationError("Keycloak email is not verified")

    return claims


def _role_candidates(roles: list[str], groups: list[str]) -> set[str]:
    """Normalize roles and (possibly path-style) groups into comparable tokens.

    Keycloak emits group memberships as full paths (e.g. ``/admins`` or
    ``/ops/admins``), not bare names, so each path segment is considered. A
    trailing-``s`` plural is also folded to its singular so the conventional
    ``/admins`` / ``/operators`` / ``/viewers`` groups map onto the app roles.
    """
    candidates: set[str] = {r.strip().lower() for r in roles if r and r.strip()}
    for group in groups:
        for segment in (group or "").split("/"):
            token = segment.strip().lower()
            if not token:
                continue
            candidates.add(token)
            if token.endswith("s"):
                candidates.add(token[:-1])
    return candidates


def map_sso_role(roles: list[str], groups: list[str]) -> str:
    """Map Keycloak realm/client roles or groups to a local app role."""
    candidates = _role_candidates(roles, groups)
    if "admin" in candidates:
        return "admin"
    if "viewer" in candidates:
        return "viewer"
    if "operator" in candidates:
        return "operator"
    for candidate in candidates:
        if candidate in _APP_ROLES:
            return candidate
    return "operator"


async def upsert_user_from_sso_claims(claims: SSOClaims, db: AsyncSession) -> User:
    """Create or update a local User matched by verified email."""
    mapped_role = map_sso_role(claims.roles, claims.groups)
    now = datetime.utcnow()

    result = await db.execute(select(User).where(User.email == claims.email))
    user = result.scalar_one_or_none()

    if user:
        user.full_name = claims.full_name or user.full_name
        user.role = mapped_role
        user.is_active = claims.enabled
        user.last_login = now
        user.updated_at = now
        await db.commit()
        await db.refresh(user)
        logger.info("sso_user_updated", user_id=str(user.id), email=claims.email)
        return user

    org_id = claims.organization_id or settings.KEYCLOAK_DEFAULT_ORGANIZATION_ID or None
    if not org_id:
        raise SSOValidationError(
            "No local user for this email and no organization_id in token or "
            "KEYCLOAK_DEFAULT_ORGANIZATION_ID — cannot JIT provision"
        )

    user = User(
        email=claims.email,
        hashed_password=_disabled_login_hash(),
        full_name=claims.full_name,
        organization_id=org_id,
        role=mapped_role,
        is_active=claims.enabled,
        last_login=now,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent first-login provisioned the same email; reuse that row.
        await db.rollback()
        result = await db.execute(select(User).where(User.email == claims.email))
        existing = result.scalar_one_or_none()
        if existing is None:
            raise
        logger.info("sso_user_provision_race", email=claims.email)
        return existing
    await db.refresh(user)
    logger.info("sso_user_provisioned", user_id=str(user.id), email=claims.email)
    return user


async def authenticate_sso_token(token: str, db: AsyncSession) -> Optional[User]:
    """Validate a Keycloak token and return the provisioned local user, or None."""
    if not _is_keycloak_configured():
        return None
    try:
        claims = await verify_keycloak_token(token)
        return await upsert_user_from_sso_claims(claims, db)
    except SSOValidationError as exc:
        logger.warning("sso_authentication_failed", error=str(exc))
        return None
    except JWTError as exc:
        logger.warning("sso_jwt_error", error=str(exc))
        return None
