"""Security primitives and delivery state for one-time user invitations."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID

import structlog
from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import get_db
from app.db.models import UserInvitation
from app.services.email_service import (
    EmailConfigurationError,
    EmailDeliveryError,
    send_user_invitation_email,
)


_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
logger = structlog.get_logger()


class InvitationTokenError(ValueError):
    """Raised when a public invitation credential is malformed."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def invitation_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_invitation_token(organization_id: UUID) -> tuple[str, str]:
    """Return an org-routable 256-bit credential and its one-way hash."""

    secret = secrets.token_urlsafe(32)
    token = f"{organization_id}.{secret}"
    return token, invitation_token_hash(token)


def invitation_token_organization(token: str) -> UUID:
    try:
        raw_org_id, secret = token.split(".", 1)
        organization_id = UUID(raw_org_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvitationTokenError("Invalid invitation token") from exc
    if not _SECRET_RE.fullmatch(secret):
        raise InvitationTokenError("Invalid invitation token")
    return organization_id


async def get_invitation_tenant_db(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Bind a public invite request to the tenant encoded in its credential."""

    try:
        payload = await request.json()
        token = payload.get("token") if isinstance(payload, dict) else None
        organization_id = invitation_token_organization(token)
    except (InvitationTokenError, TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Invitation not found")

    if db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT set_config('app.current_org_id', :org_id, true)"),
            {"org_id": str(organization_id)},
        )
    yield db


def invitation_url(token: str) -> str:
    base_url = settings.USER_INVITE_PUBLIC_BASE_URL.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise EmailConfigurationError(
            "USER_INVITE_PUBLIC_BASE_URL must be an HTTP(S) origin or path"
        )
    return f"{base_url}/accept-invite#token={token}"


def validate_new_password(password: str) -> None:
    if len(password) < settings.USER_PASSWORD_MIN_LENGTH:
        raise ValueError(
            "Password must be at least "
            f"{settings.USER_PASSWORD_MIN_LENGTH} characters"
        )
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes")


async def deliver_invitation(
    invitation: UserInvitation,
    *,
    token: str,
    organization_name: str,
) -> bool:
    """Attempt SMTP delivery and persist only bounded outcome metadata."""

    now = utcnow()
    invitation.delivery_attempts = (invitation.delivery_attempts or 0) + 1
    invitation.last_delivery_attempt_at = now
    invitation.updated_at = now
    try:
        url = invitation_url(token)
        await send_user_invitation_email(
            invitation.normalized_email,
            organization_name,
            invitation.requested_role,
            url,
            invitation.expires_at,
            max_attempts=settings.USER_INVITE_EMAIL_MAX_ATTEMPTS,
        )
    except EmailConfigurationError:
        invitation.delivery_status = "failed"
        invitation.delivery_error_code = "smtp_not_configured"
        return False
    except EmailDeliveryError:
        invitation.delivery_status = "failed"
        invitation.delivery_error_code = "smtp_delivery_failed"
        return False
    except Exception as exc:
        # The invitation is already committed before delivery. Preserve a
        # bounded, retryable outcome even if a transport implementation raises
        # an unexpected exception; never persist the raw token or full URL.
        invitation.delivery_status = "failed"
        invitation.delivery_error_code = "smtp_delivery_failed"
        logger.warning(
            "user_invitation_delivery_failed",
            invitation_id=str(invitation.id),
            error_type=type(exc).__name__,
        )
        return False

    invitation.delivery_status = "sent"
    invitation.delivery_error_code = None
    invitation.delivered_at = now
    return True
