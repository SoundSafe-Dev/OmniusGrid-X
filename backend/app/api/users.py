"""Tenant-scoped user administration and one-time invitation acceptance."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import Query, APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import conflict_response
from app.api.auth import get_password_hash
from app.core.config import settings
from app.core.pagination import MAX_OFFSET
from app.core.session import SessionManager
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import Organization, User, UserInvitation
from app.services.tenant_quotas import check_seat_quota
from app.middleware.rate_limit import auth_rate_limit
from app.middleware.rbac import require_admin
from app.services.user_audit import add_user_audit
from app.services.user_invitations import (
    InvitationTokenError,
    deliver_invitation,
    get_invitation_tenant_db,
    invitation_token_hash,
    invitation_token_organization,
    issue_invitation_token,
    normalize_email,
    utcnow,
    validate_new_password,
)


router = APIRouter(dependencies=[Depends(require_admin)])
public_router = APIRouter()

UserRole = Literal["admin", "operator", "viewer"]
InvitationStatus = Literal["pending", "accepted", "revoked", "expired"]
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str:
    normalized = normalize_email(value)
    if len(normalized) > 320 or not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("Enter a valid email address")
    return normalized


def _not_found(resource: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{resource} not found")


def _same_id(left: UUID | str | None, right: UUID | str | None) -> bool:
    """Compare UUID identifiers independently of ORM result representation."""

    return left is not None and right is not None and str(left) == str(right)


def _invitation_invalid() -> HTTPException:
    return HTTPException(status_code=404, detail="Invitation not found")


def _invitation_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Invitation is no longer valid",
    )


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_expired(invitation: UserInvitation, now: datetime | None = None) -> bool:
    return _as_aware(invitation.expires_at) <= (now or utcnow())


def _clean_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Name may not be blank")
    return cleaned


def _sqlstate(exc: IntegrityError) -> str | None:
    original = exc.orig
    cause = getattr(original, "__cause__", None)
    return (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
        or getattr(cause, "sqlstate", None)
        or getattr(cause, "pgcode", None)
    )


async def _commit_unique_conflict(
    db: AsyncSession,
    *,
    detail: str,
) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if _sqlstate(exc) == "23505":
            raise HTTPException(status_code=409, detail=detail) from exc
        raise


class UserResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    email: str
    name: str
    #: OPTIONAL, because `users.full_name` is nullable with no server default. A required
    #: field over a nullable column means a perfectly valid row cannot be serialised —
    #: pydantic raises inside the handler and FastAPI answers 500, naming a validation error
    #: in our own schema rather than anything about the data. A Python-side ORM default does
    #: not save it: that fires only for rows written through SQLAlchemy, and a migration
    #: backfill or a raw INSERT writes NULL straight past it.
    full_name: str | None = None
    role: UserRole
    organization_id: UUID = Field(alias="organizationId")
    is_active: bool = Field(alias="isActive")
    last_login_at: datetime | None = Field(alias="lastLoginAt")
    created_at: datetime | None = Field(alias="createdAt")
    updated_at: datetime | None = Field(alias="updatedAt")


class UserListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[UserResponse]
    total: int
    skip: int
    limit: int
    has_more: bool = Field(alias="hasMore")


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    role: UserRole | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return _validate_email(value) if value is not None else None


class InvitationCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    role: UserRole

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class InvitationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    email: str
    role: UserRole
    status: InvitationStatus
    expires_at: datetime = Field(alias="expiresAt")
    delivery_status: Literal["pending", "sent", "failed"] = Field(
        alias="deliveryStatus"
    )
    delivery_attempts: int = Field(alias="deliveryAttempts")
    delivery_error_code: str | None = Field(alias="deliveryErrorCode")
    delivered_at: datetime | None = Field(alias="deliveredAt")
    created_by: UUID | None = Field(alias="createdBy")
    accepted_user_id: UUID | None = Field(alias="acceptedUserId")
    accepted_at: datetime | None = Field(alias="acceptedAt")
    revoked_at: datetime | None = Field(alias="revokedAt")
    created_at: datetime | None = Field(alias="createdAt")
    updated_at: datetime | None = Field(alias="updatedAt")


class InvitationListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[InvitationResponse]
    total: int
    skip: int
    limit: int
    has_more: bool = Field(alias="hasMore")


class InvitationTokenRequest(BaseModel):
    token: str = Field(..., min_length=80, max_length=100)


class InvitationAcceptRequest(InvitationTokenRequest):
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        try:
            validate_new_password(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return value


class InvitationValidationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    role: UserRole
    organization_name: str = Field(alias="organizationName")
    expires_at: datetime = Field(alias="expiresAt")


class InvitationAcceptanceResponse(BaseModel):
    message: str
    user: UserResponse


def _user_response(user: User) -> UserResponse:
    full_name = user.full_name or ""
    return UserResponse(
        id=user.id,
        email=user.email,
        name=full_name,
        full_name=full_name,
        role=user.role,
        organization_id=user.organization_id,
        is_active=bool(user.is_active),
        last_login_at=user.last_login,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _invitation_response(invitation: UserInvitation) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        email=invitation.normalized_email,
        role=invitation.requested_role,
        status=invitation.status,
        expires_at=invitation.expires_at,
        delivery_status=invitation.delivery_status,
        delivery_attempts=invitation.delivery_attempts,
        delivery_error_code=invitation.delivery_error_code,
        delivered_at=invitation.delivered_at,
        created_by=invitation.created_by,
        accepted_user_id=invitation.accepted_user_id,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
        created_at=invitation.created_at,
        updated_at=invitation.updated_at,
    )


async def _locked_tenant_users(
    user_id: UUID,
    organization_id: UUID,
    db: AsyncSession,
) -> tuple[User, list[User]]:
    """Lock tenant users in a stable order so last-admin checks cannot race."""

    result = await db.execute(
        select(User)
        .where(User.organization_id == organization_id)
        .order_by(User.id)
        .with_for_update()
    )
    users = list(result.scalars().all())
    target = next(
        (candidate for candidate in users if _same_id(candidate.id, user_id)),
        None,
    )
    if target is None:
        raise _not_found("User")
    return target, users


def _active_admin_count(users: list[User]) -> int:
    return sum(
        1
        for user in users
        if user.is_active and user.role == "admin"
    )


async def _tenant_invitation(
    invitation_id: UUID,
    organization_id: UUID,
    db: AsyncSession,
    *,
    lock: bool = False,
) -> UserInvitation:
    query = select(UserInvitation).where(
        UserInvitation.id == invitation_id,
        UserInvitation.organization_id == organization_id,
    )
    if lock:
        query = query.with_for_update()
    invitation = (await db.execute(query)).scalar_one_or_none()
    if invitation is None:
        raise _not_found("Invitation")
    return invitation


def _mark_invitation_expired(
    db: AsyncSession,
    request: Request,
    invitation: UserInvitation,
    *,
    actor_id: UUID | None,
) -> None:
    now = utcnow()
    invitation.status = "expired"
    invitation.updated_at = now
    add_user_audit(
        db,
        request,
        organization_id=invitation.organization_id,
        action="user_invitation_expired",
        resource_type="user_invitation",
        resource_id=str(invitation.id),
        actor_id=actor_id,
        details={
            "email": invitation.normalized_email,
            "role": invitation.requested_role,
            "expired_at": now.isoformat(),
        },
    )


async def _expire_pending_invitations(
    db: AsyncSession,
    request: Request,
    organization_id: UUID,
    *,
    actor_id: UUID | None,
) -> int:
    now = utcnow()
    result = await db.execute(
        select(UserInvitation)
        .where(
            UserInvitation.organization_id == organization_id,
            UserInvitation.status == "pending",
            UserInvitation.expires_at <= now,
        )
        .order_by(UserInvitation.id)
        .with_for_update()
    )
    invitations = list(result.scalars().all())
    for invitation in invitations:
        _mark_invitation_expired(
            db,
            request,
            invitation,
            actor_id=actor_id,
        )
    return len(invitations)


async def _organization_name(
    organization_id: UUID,
    db: AsyncSession,
) -> str:
    result = await db.execute(
        select(Organization.name).where(Organization.id == organization_id)
    )
    name = result.scalar_one_or_none()
    if name is None:
        raise _not_found("Organization")
    return name


async def _record_delivery(
    db: AsyncSession,
    request: Request,
    invitation: UserInvitation,
    *,
    token: str,
    organization_name: str,
    actor_id: UUID,
) -> None:
    delivered = await deliver_invitation(
        invitation,
        token=token,
        organization_name=organization_name,
    )
    add_user_audit(
        db,
        request,
        organization_id=invitation.organization_id,
        action=(
            "user_invitation_delivery_succeeded"
            if delivered
            else "user_invitation_delivery_failed"
        ),
        resource_type="user_invitation",
        resource_id=str(invitation.id),
        actor_id=actor_id,
        details={
            "delivery_status": invitation.delivery_status,
            "delivery_attempt": invitation.delivery_attempts,
            "error_code": invitation.delivery_error_code,
        },
    )
    await db.commit()


async def _public_invitation(
    token: str,
    db: AsyncSession,
    *,
    lock: bool,
) -> UserInvitation:
    try:
        organization_id = invitation_token_organization(token)
    except InvitationTokenError as exc:
        raise _invitation_invalid() from exc

    # The org prefix only selects an RLS partition. Possession of the full
    # random credential is still required because lookup uses its SHA-256 hash.
    await db.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(organization_id)},
    )
    query = select(UserInvitation).where(
        UserInvitation.organization_id == organization_id,
        UserInvitation.token_hash == invitation_token_hash(token),
    )
    if lock:
        query = query.with_for_update()
    invitation = (await db.execute(query)).scalar_one_or_none()
    if invitation is None:
        raise _invitation_invalid()
    return invitation


@router.get("", response_model=UserListResponse)
async def list_users(
    # DECLARED, not just validated. The handler already refused skip<0 / limit>500 with a
    # 422 — correct behaviour that OpenAPI could not see, so the contract gate could not
    # check it and the generated SDK would not carry it. `Query` does both.
    skip: int = Query(0, ge=0, le=MAX_OFFSET, description="Rows to skip."),
    limit: int = Query(100, ge=1, le=500, description="Maximum rows to return."),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> UserListResponse:
    if skip < 0 or limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="Invalid pagination")
    total = (
        await db.execute(
            select(func.count(User.id)).where(
                User.organization_id == organization_id
            )
        )
    ).scalar_one()
    result = await db.execute(
        select(User)
        .where(User.organization_id == organization_id)
        .order_by(User.created_at.desc(), User.id)
        .offset(skip)
        .limit(limit)
    )
    items = [_user_response(user) for user in result.scalars().all()]
    return UserListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
        has_more=skip + len(items) < total,
    )


@router.get("/invitations", response_model=InvitationListResponse)
async def list_invitations(
    request: Request,
    # DECLARED, not just validated. The handler already refused skip<0 / limit>500 with a
    # 422 — correct behaviour that OpenAPI could not see, so the contract gate could not
    # check it and the generated SDK would not carry it. `Query` does both.
    skip: int = Query(0, ge=0, le=MAX_OFFSET, description="Rows to skip."),
    limit: int = Query(100, ge=1, le=500, description="Maximum rows to return."),
    invitation_status: InvitationStatus | None = None,
    current_user: User = Depends(require_admin),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> InvitationListResponse:
    if skip < 0 or limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="Invalid pagination")
    if await _expire_pending_invitations(
        db,
        request,
        organization_id,
        actor_id=current_user.id,
    ):
        await db.commit()

    filters = [UserInvitation.organization_id == organization_id]
    if invitation_status is not None:
        filters.append(UserInvitation.status == invitation_status)
    total = (
        await db.execute(select(func.count(UserInvitation.id)).where(*filters))
    ).scalar_one()
    result = await db.execute(
        select(UserInvitation)
        .where(*filters)
        .order_by(UserInvitation.created_at.desc(), UserInvitation.id)
        .offset(skip)
        .limit(limit)
    )
    items = [
        _invitation_response(invitation)
        for invitation in result.scalars().all()
    ]
    return InvitationListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
        has_more=skip + len(items) < total,
    )


@router.post(
    "/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={**conflict_response},
)
async def create_invitation(
    request: Request,
    body: InvitationCreate,
    current_user: User = Depends(require_admin),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> InvitationResponse:
    now = utcnow()
    if await _expire_pending_invitations(
        db,
        request,
        organization_id,
        actor_id=current_user.id,
    ):
        await db.flush()

    # FS-842. Gated HERE rather than at acceptance, and after expiry has been swept so the
    # count reflects seats actually held. Refusing at invitation time tells the admin who
    # can act; refusing at acceptance would send an invitation, let someone click it, and
    # then reject the person invited — for a reason they cannot do anything about.
    #
    # An invitation issued under the limit and accepted after somebody else takes the last
    # seat is deliberately allowed through: the organisation already committed to that
    # person, and revoking on arrival is the worse of the two failures.
    seat_rejection = await check_seat_quota(db, organization_id)
    if seat_rejection is not None:
        raise HTTPException(
            status_code=seat_rejection.status, detail=seat_rejection.detail
        )

    existing_user = (
        await db.execute(
            select(User.id).where(func.lower(User.email) == body.email)
        )
    ).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="Email is unavailable")

    existing_invitation = (
        await db.execute(
            select(UserInvitation.id).where(
                UserInvitation.organization_id == organization_id,
                UserInvitation.normalized_email == body.email,
                UserInvitation.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if existing_invitation is not None:
        raise HTTPException(
            status_code=409,
            detail="A pending invitation already exists for this email",
        )

    token, token_hash = issue_invitation_token(organization_id)
    invitation = UserInvitation(
        organization_id=organization_id,
        normalized_email=body.email,
        requested_role=body.role,
        token_hash=token_hash,
        status="pending",
        expires_at=now + timedelta(hours=settings.USER_INVITE_EXPIRE_HOURS),
        delivery_status="pending",
        delivery_attempts=0,
        created_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(invitation)
    await db.flush()
    add_user_audit(
        db,
        request,
        organization_id=organization_id,
        action="user_invitation_created",
        resource_type="user_invitation",
        resource_id=str(invitation.id),
        actor_id=current_user.id,
        details={
            "email": invitation.normalized_email,
            "role": invitation.requested_role,
            "expires_at": invitation.expires_at.isoformat(),
        },
    )

    # Persist the credential hash before attempting an external side effect.
    await _commit_unique_conflict(
        db,
        detail="A pending invitation already exists for this email",
    )
    organization_name = await _organization_name(organization_id, db)
    await _record_delivery(
        db,
        request,
        invitation,
        token=token,
        organization_name=organization_name,
        actor_id=current_user.id,
    )
    return _invitation_response(invitation)


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=InvitationResponse,
)
async def resend_invitation(
    invitation_id: UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> InvitationResponse:
    invitation = await _tenant_invitation(
        invitation_id,
        organization_id,
        db,
        lock=True,
    )
    if invitation.status != "pending":
        raise _invitation_unavailable()
    if _is_expired(invitation):
        _mark_invitation_expired(
            db,
            request,
            invitation,
            actor_id=current_user.id,
        )
        await db.commit()
        raise _invitation_unavailable()

    now = utcnow()
    token, token_hash = issue_invitation_token(organization_id)
    invitation.token_hash = token_hash
    invitation.expires_at = now + timedelta(
        hours=settings.USER_INVITE_EXPIRE_HOURS
    )
    invitation.delivery_status = "pending"
    invitation.delivery_error_code = None
    invitation.delivered_at = None
    invitation.updated_at = now
    add_user_audit(
        db,
        request,
        organization_id=organization_id,
        action="user_invitation_resent",
        resource_type="user_invitation",
        resource_id=str(invitation.id),
        actor_id=current_user.id,
        details={
            "email": invitation.normalized_email,
            "role": invitation.requested_role,
            "expires_at": invitation.expires_at.isoformat(),
            "delivery_attempt": invitation.delivery_attempts + 1,
        },
    )
    # Rotating the hash first invalidates every previously emailed link.
    await db.commit()
    organization_name = await _organization_name(organization_id, db)
    await _record_delivery(
        db,
        request,
        invitation,
        token=token,
        organization_name=organization_name,
        actor_id=current_user.id,
    )
    return _invitation_response(invitation)


@router.delete(
    "/invitations/{invitation_id}",
    response_model=InvitationResponse,
)
async def revoke_invitation(
    invitation_id: UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> InvitationResponse:
    invitation = await _tenant_invitation(
        invitation_id,
        organization_id,
        db,
        lock=True,
    )
    if invitation.status != "pending":
        raise _invitation_unavailable()
    if _is_expired(invitation):
        _mark_invitation_expired(
            db,
            request,
            invitation,
            actor_id=current_user.id,
        )
        await db.commit()
        raise _invitation_unavailable()

    now = utcnow()
    invitation.status = "revoked"
    invitation.revoked_at = now
    invitation.updated_at = now
    add_user_audit(
        db,
        request,
        organization_id=organization_id,
        action="user_invitation_revoked",
        resource_type="user_invitation",
        resource_id=str(invitation.id),
        actor_id=current_user.id,
        details={
            "email": invitation.normalized_email,
            "role": invitation.requested_role,
        },
    )
    await db.commit()
    return _invitation_response(invitation)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> UserResponse:
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.organization_id == organization_id,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise _not_found("User")
    return _user_response(user)


@router.patch("/{user_id}", response_model=UserResponse, responses={**conflict_response})
async def update_user(
    user_id: UUID,
    request: Request,
    body: UserUpdate,
    current_user: User = Depends(require_admin),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> UserResponse:
    target, tenant_users = await _locked_tenant_users(
        user_id,
        organization_id,
        db,
    )
    supplied = body.model_fields_set
    new_name = (
        _clean_name(body.name)
        if "name" in supplied and body.name is not None
        else target.full_name
    )
    new_email = body.email if "email" in supplied else target.email
    new_role = body.role if "role" in supplied else target.role

    if "name" in supplied and body.name is None:
        raise HTTPException(status_code=422, detail="Name may not be null")
    if "email" in supplied and body.email is None:
        raise HTTPException(status_code=422, detail="Email may not be null")
    if "role" in supplied and body.role is None:
        raise HTTPException(status_code=422, detail="Role may not be null")
    if _same_id(target.id, current_user.id) and new_role != target.role:
        raise HTTPException(
            status_code=409,
            detail="You cannot change your own role",
        )
    if (
        target.is_active
        and target.role == "admin"
        and new_role != "admin"
        and _active_admin_count(tenant_users) <= 1
    ):
        raise HTTPException(
            status_code=409,
            detail="The organization must retain an active admin",
        )

    if new_email != target.email:
        conflict = (
            await db.execute(
                select(User.id).where(
                    func.lower(User.email) == new_email,
                    User.id != target.id,
                )
            )
        ).scalar_one_or_none()
        if conflict is not None:
            raise HTTPException(status_code=409, detail="Email is unavailable")

    before = {
        "name": target.full_name or "",
        "email": target.email,
        "role": target.role,
    }
    name_changed = new_name != target.full_name
    email_changed = new_email != target.email
    role_changed = new_role != target.role
    if not (name_changed or email_changed or role_changed):
        return _user_response(target)

    now = utcnow()
    target.full_name = new_name
    target.email = new_email
    target.role = new_role
    target.updated_at = now
    after = {"name": new_name, "email": new_email, "role": new_role}

    if name_changed:
        add_user_audit(
            db,
            request,
            organization_id=organization_id,
            action="user_profile_updated",
            resource_type="user",
            resource_id=str(target.id),
            actor_id=current_user.id,
            details={"before": {"name": before["name"]}, "after": {"name": new_name}},
        )
    if email_changed:
        add_user_audit(
            db,
            request,
            organization_id=organization_id,
            action="user_email_changed",
            resource_type="user",
            resource_id=str(target.id),
            actor_id=current_user.id,
            details={
                "before": {"email": before["email"]},
                "after": {"email": new_email},
            },
        )
    if role_changed:
        add_user_audit(
            db,
            request,
            organization_id=organization_id,
            action="user_role_changed",
            resource_type="user",
            resource_id=str(target.id),
            actor_id=current_user.id,
            details={
                "before": {"role": before["role"]},
                "after": {"role": new_role},
            },
        )
        revoked_count = await SessionManager.revoke_all_user_sessions(
            target.id,
            db,
            reason="role_changed",
        )
        add_user_audit(
            db,
            request,
            organization_id=organization_id,
            action="user_sessions_revoked",
            resource_type="user",
            resource_id=str(target.id),
            actor_id=current_user.id,
            details={"reason": "role_changed", "session_count": revoked_count},
        )

    await _commit_unique_conflict(db, detail="Email is unavailable")
    return _user_response(target)


@router.delete("/{user_id}", response_model=UserResponse, responses={**conflict_response})
async def deactivate_user(
    user_id: UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> UserResponse:
    target, tenant_users = await _locked_tenant_users(
        user_id,
        organization_id,
        db,
    )
    if _same_id(target.id, current_user.id):
        raise HTTPException(
            status_code=409,
            detail="You cannot deactivate your own account",
        )
    if not target.is_active:
        raise HTTPException(status_code=409, detail="User is already inactive")
    if (
        target.role == "admin"
        and _active_admin_count(tenant_users) <= 1
    ):
        raise HTTPException(
            status_code=409,
            detail="The organization must retain an active admin",
        )

    target.is_active = False
    target.updated_at = utcnow()
    revoked_count = await SessionManager.revoke_all_user_sessions(
        target.id,
        db,
        reason="user_deactivated",
    )
    add_user_audit(
        db,
        request,
        organization_id=organization_id,
        action="user_deactivated",
        resource_type="user",
        resource_id=str(target.id),
        actor_id=current_user.id,
        details={"email": target.email, "role": target.role},
    )
    add_user_audit(
        db,
        request,
        organization_id=organization_id,
        action="user_sessions_revoked",
        resource_type="user",
        resource_id=str(target.id),
        actor_id=current_user.id,
        details={"reason": "user_deactivated", "session_count": revoked_count},
    )
    await db.commit()
    return _user_response(target)


@router.post("/{user_id}/reactivate", response_model=UserResponse, responses={**conflict_response})
async def reactivate_user(
    user_id: UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> UserResponse:
    target, _ = await _locked_tenant_users(user_id, organization_id, db)
    if target.is_active:
        raise HTTPException(status_code=409, detail="User is already active")

    # FS-842. REACTIVATION CONSUMES A SEAT, and a quota enforced only on creation is
    # bypassed by deactivating and reactivating — which is a normal administrative action,
    # not an attack, so it would have been found by an admin rather than reported.
    seat_rejection = await check_seat_quota(db, organization_id)
    if seat_rejection is not None:
        raise HTTPException(
            status_code=seat_rejection.status, detail=seat_rejection.detail
        )

    target.is_active = True
    target.updated_at = utcnow()
    add_user_audit(
        db,
        request,
        organization_id=organization_id,
        action="user_reactivated",
        resource_type="user",
        resource_id=str(target.id),
        actor_id=current_user.id,
        details={
            "email": target.email,
            "role": target.role,
            "sessions_restored": False,
        },
    )
    await db.commit()
    return _user_response(target)


@public_router.post(
    "/validate",
    response_model=InvitationValidationResponse,
)
@auth_rate_limit(settings.AUTH_INVITE_VALIDATE_RATE_LIMIT)
async def validate_invitation(
    request: Request,
    body: InvitationTokenRequest,
    db: AsyncSession = Depends(get_invitation_tenant_db),
) -> InvitationValidationResponse:
    invitation = await _public_invitation(body.token, db, lock=True)
    if invitation.status != "pending":
        raise _invitation_unavailable()
    if _is_expired(invitation):
        _mark_invitation_expired(
            db,
            request,
            invitation,
            actor_id=None,
        )
        await db.commit()
        raise _invitation_unavailable()

    organization_name = await _organization_name(
        invitation.organization_id,
        db,
    )
    return InvitationValidationResponse(
        email=invitation.normalized_email,
        role=invitation.requested_role,
        organization_name=organization_name,
        expires_at=invitation.expires_at,
    )


@public_router.post(
    "/accept",
    response_model=InvitationAcceptanceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={**conflict_response},
)
@auth_rate_limit(settings.AUTH_INVITE_ACCEPT_RATE_LIMIT)
async def accept_invitation(
    request: Request,
    body: InvitationAcceptRequest,
    db: AsyncSession = Depends(get_invitation_tenant_db),
) -> InvitationAcceptanceResponse:
    invitation = await _public_invitation(body.token, db, lock=True)
    if invitation.status != "pending":
        raise _invitation_unavailable()
    if _is_expired(invitation):
        _mark_invitation_expired(
            db,
            request,
            invitation,
            actor_id=None,
        )
        await db.commit()
        raise _invitation_unavailable()

    existing_user = (
        await db.execute(
            select(User.id).where(
                func.lower(User.email) == invitation.normalized_email
            )
        )
    ).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(status_code=409, detail="Email is unavailable")

    now = utcnow()
    user = User(
        email=invitation.normalized_email,
        hashed_password=get_password_hash(body.password),
        full_name=_clean_name(body.name),
        organization_id=invitation.organization_id,
        role=invitation.requested_role,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.flush()
    invitation.status = "accepted"
    invitation.accepted_user_id = user.id
    invitation.accepted_at = now
    invitation.updated_at = now
    add_user_audit(
        db,
        request,
        organization_id=invitation.organization_id,
        action="user_invitation_accepted",
        resource_type="user_invitation",
        resource_id=str(invitation.id),
        actor_id=user.id,
        details={
            "user_id": str(user.id),
            "email": invitation.normalized_email,
            "role": invitation.requested_role,
        },
    )
    add_user_audit(
        db,
        request,
        organization_id=invitation.organization_id,
        action="user_created",
        resource_type="user",
        resource_id=str(user.id),
        actor_id=user.id,
        details={
            "source": "invitation",
            "invitation_id": str(invitation.id),
            "email": user.email,
            "role": user.role,
        },
    )
    await _commit_unique_conflict(db, detail="Email is unavailable")
    return InvitationAcceptanceResponse(
        message="Invitation accepted. Sign in with your new account.",
        user=_user_response(user),
    )
