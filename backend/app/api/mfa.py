"""Enrol, confirm and disable a TOTP second factor (FS-750).

800-171 **3.5.3** — multifactor for local and network access to privileged accounts. Named
CMMC L2 practice, no partial credit.

WHY THIS ROUTER EXISTS AND `keycloak_service.enable_mfa` DID NOT SUFFICE. Those helpers were
unreachable — on this repository's own orphaned-definition list, present and called by
nothing — and even wired they would only serve deployments running Keycloak, which is
disabled by default. A practice covering *local* access needs a local implementation.

THE ENROLMENT IS TWO-STEP ON PURPOSE. `POST /enroll` issues a secret and returns it once;
`POST /confirm` activates it only after the user proves a working code. An account that
believes it has MFA and does not is worse than one that knows it has none — the user stops
worrying about their password, and the control is absent exactly where it is being counted.
`confirmed_at` is that distinction, and nothing treats an unconfirmed row as protection.

RECOVERY CODES ARE SHOWN ONCE, at confirmation, and stored only as digests. A second factor
with no recovery path becomes a support process that disables it on request — which is a
second factor an attacker can talk their way past.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core import mfa as totp
from app.core.responses import conflict_response
from app.core.tenant import get_tenant_db
from app.db.models import User, UserMFA
from app.services.audit import record_audit

logger = structlog.get_logger()
router = APIRouter()


class EnrollResponse(BaseModel):
    secret: str = Field(description="Base32 TOTP secret. Shown once; store it now.")
    provisioning_uri: str = Field(description="otpauth:// URI for an authenticator app")
    already_enrolled: bool = False


class ConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class ConfirmResponse(BaseModel):
    confirmed: bool
    recovery_codes: List[str] = Field(
        description="Shown ONCE. Stored only as digests; they cannot be recovered."
    )


class MFAStatus(BaseModel):
    enrolled: bool
    confirmed: bool
    recovery_codes_remaining: int


async def _row_for(db: AsyncSession, user: User) -> Optional[UserMFA]:
    return (
        await db.execute(select(UserMFA).where(UserMFA.user_id == user.id))
    ).scalar_one_or_none()


@router.get("/status", response_model=MFAStatus, summary="This account's MFA state")
async def mfa_status(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    row = await _row_for(db, current_user)
    return {
        "enrolled": row is not None,
        "confirmed": bool(row and row.confirmed_at),
        "recovery_codes_remaining": len(row.recovery_code_hashes or []) if row else 0,
    }


@router.post(
    "/enroll",
    response_model=EnrollResponse,
    summary="Begin TOTP enrolment",
    responses={**conflict_response},
)
async def enroll(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Issue a secret. It is NOT active until `/confirm` accepts a code from it."""
    row = await _row_for(db, current_user)
    if row and row.confirmed_at:
        # Re-enrolling would silently invalidate a working authenticator, and doing that
        # from a session an attacker already holds is a way to lock the owner out. Disable
        # first, deliberately.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MFA is already enabled; disable it before enrolling again",
        )

    secret = totp.generate_secret()
    if row is None:
        row = UserMFA(
            user_id=current_user.id,
            organization_id=current_user.organization_id,
            encrypted_secret=totp.encrypt_secret(secret),
            recovery_code_hashes=[],
        )
        db.add(row)
    else:
        # An abandoned, unconfirmed enrolment. Replacing its secret is safe precisely
        # because it never protected anything.
        row.encrypted_secret = totp.encrypt_secret(secret)
        row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "secret": secret,
        "provisioning_uri": totp.provisioning_uri(secret, current_user.email),
        "already_enrolled": False,
    }


@router.post(
    "/confirm",
    response_model=ConfirmResponse,
    summary="Activate TOTP",
    responses={**conflict_response},
)
async def confirm(
    body: ConfirmRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    row = await _row_for(db, current_user)
    if row is None:
        raise HTTPException(status_code=404, detail="No enrolment in progress")
    if row.confirmed_at:
        raise HTTPException(status_code=409, detail="MFA is already enabled")

    ok, window = totp.verify_code(
        totp.decrypt_secret(row.encrypted_secret),
        body.code,
        last_used_window=row.last_used_window,
    )
    if not ok:
        row.failed_attempts = (row.failed_attempts or 0) + 1
        await db.commit()
        raise HTTPException(status_code=400, detail="Incorrect code")

    codes = totp.generate_recovery_codes()
    row.recovery_code_hashes = [totp.hash_recovery_code(c) for c in codes]
    row.confirmed_at = datetime.now(timezone.utc)
    row.last_used_window = window
    row.failed_attempts = 0
    row.updated_at = datetime.now(timezone.utc)
    await record_audit(
        action="user_mfa_enabled",
        resource_type="user",
        resource_id=str(current_user.id),
        actor_id=current_user.id,
        organization_id=current_user.organization_id,
        session=db,
    )
    await db.commit()
    logger.info("mfa_enabled", user_id=str(current_user.id))
    return {"confirmed": True, "recovery_codes": codes}


@router.delete("/", status_code=204, summary="Disable TOTP for this account")
async def disable(
    body: ConfirmRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Disabling REQUIRES a current code or a recovery code.

    Otherwise a stolen session token removes the second factor, which makes the factor
    worth exactly as much as the session — i.e. nothing.
    """
    row = await _row_for(db, current_user)
    if row is None or not row.confirmed_at:
        raise HTTPException(status_code=404, detail="MFA is not enabled")

    ok, _window = totp.verify_code(
        totp.decrypt_secret(row.encrypted_secret),
        body.code,
        last_used_window=row.last_used_window,
    )
    if not ok:
        ok, _remaining = totp.consume_recovery_code(
            body.code, row.recovery_code_hashes or []
        )
    if not ok:
        raise HTTPException(status_code=400, detail="Incorrect code")

    await db.delete(row)
    await record_audit(
        action="user_mfa_disabled",
        resource_type="user",
        resource_id=str(current_user.id),
        actor_id=current_user.id,
        organization_id=current_user.organization_id,
        session=db,
    )
    await db.commit()
    logger.warning("mfa_disabled", user_id=str(current_user.id))
