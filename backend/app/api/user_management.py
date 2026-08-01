"""Admin user management (FS-221).

Only ``GET /auth/users`` existed, which is why ``pages/admin/AdminPages.tsx``
hard-coded ``USER_MGMT_ENABLED = false`` and disabled the whole surface: there was
no way to invite, edit, deactivate or change the role of a user through the
product.

SESSION CHOICE. ``get_tenant_db`` rather than ``get_db``, even though ``users``
has no RLS policy: ``audit_logs`` DOES, so the audit writes below need
``app.current_org_id`` set on the session. Using ``get_db`` here made every audit
insert fail the RLS check.

TENANCY IS EXPLICIT HERE, AND HAS TO BE. ``users`` is **not** an RLS-protected
table — it is absent from migrations 011/033 — so ``app.current_org_id`` does
nothing for it and a query that forgets its predicate returns every tenant's users.
That is the same shape as the alarms leak (FS-216), which is why every statement
below goes through :func:`_own_org_user` or filters ``organization_id`` inline, and
why the tests assert each endpoint individually rather than a representative one.

DEACTIVATE, NEVER DELETE. Users are referenced by ``alarms.acknowledged_by``,
``alarm_rules.created_by``, audit rows and task assignments. Hard-deleting would
either break those references or erase the record of who did what, so
``DELETE /users/{id}`` sets ``is_active = false``.
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from types import SimpleNamespace
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user, get_password_hash
from app.core import roles as role_vocab
from app.core.pagination import MAX_OFFSET, PaginatedResponse, paginate
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.db.models import User
from app.middleware.rbac import require_admin
from app.services.audit import record_audit
from app.models.schemas import (
    UserAdminCreate,
    UserAdminResponse,
    UserAdminUpdate,
)

logger = structlog.get_logger()

# Every route here is admin-only. Declared on the router so a new endpoint cannot
# be added without the gate — the alarms leak happened one forgotten predicate at
# a time.
router = APIRouter(dependencies=[Depends(require_admin)])


async def _own_org_user(db: AsyncSession, user_id: UUID, org_id: UUID) -> User:
    """Fetch a user in ``org_id``, or 404.

    404 rather than 403 for a user in another organization, matching the
    convention elsewhere: do not confirm that an account exists in a tenant the
    caller cannot see.
    """
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.organization_id == org_id)
        )
    ).scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get(
    "/",
    response_model=PaginatedResponse[UserAdminResponse],
    summary="List users",
    description="Paginated list of users in the caller's organization. Admin only.",
)
async def list_users(
    is_active: Optional[bool] = None,
    role: Optional[str] = None,
    skip: int = Query(0, ge=0, le=MAX_OFFSET),
    limit: int = Query(50, ge=1, le=500),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    query = select(User).where(User.organization_id == org_id)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if role:
        query = query.where(User.role == role)

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return paginate(
        result.scalars().all(), total, SimpleNamespace(skip=skip, limit=limit)
    )


@router.get(
    "/{user_id}",
    response_model=UserAdminResponse,
    summary="Get a user",
    description="Retrieve one user from the caller's organization. Admin only.",
)
async def get_user(
    user_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    return await _own_org_user(db, user_id, org_id)


@router.post(
    "/",
    response_model=UserAdminResponse,
    status_code=201,
    summary="Create a user",
    description="Add a user to the caller's organization. Admin only.",
)
async def create_user(
    payload: UserAdminCreate,
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    # `users.email` is UNIQUE across the whole table, not per organization, so a
    # duplicate must be reported as a conflict rather than surfacing as an opaque
    # IntegrityError. Checked without revealing which tenant owns the address.
    existing = (
        await db.execute(select(User.id).where(User.email == payload.email))
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=get_password_hash(payload.password),
        # Server-side: the schema has no organization_id field, so a client cannot
        # place a user in another tenant.
        organization_id=org_id,
        role=payload.role,
        department=payload.department,
        is_active=True,
    )
    db.add(user)
    await db.flush()  # assign user.id before the audit row references it
    await record_audit(
        action="user_created",
        resource_type="user",
        resource_id=user.id,
        actor_id=current_user.id,
        organization_id=org_id,
        details={"email": user.email, "role": user.role},
        session=db,
    )
    await db.commit()

    logger.info(
        "user_created",
        actor_id=str(current_user.id),
        user_id=str(user.id),
        organization_id=str(org_id),
        role=user.role,
    )
    return user


@router.patch(
    "/{user_id}",
    response_model=UserAdminResponse,
    summary="Update a user",
    description="Partial update of name, department, role or active state. Admin only.",
)
async def update_user(
    user_id: UUID,
    payload: UserAdminUpdate,
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    user = await _own_org_user(db, user_id, org_id)
    changes = payload.model_dump(exclude_unset=True)

    # An admin must not be able to strand their own organization. Demoting or
    # deactivating the last active admin would leave nobody who can manage users,
    # and the only recovery would be direct database access.
    losing_admin = (
        user.role == role_vocab.ADMIN
        and (
            changes.get("role", user.role) != role_vocab.ADMIN
            or changes.get("is_active", user.is_active) is False
        )
    )
    if losing_admin:
        remaining = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.organization_id == org_id,
                    User.role == role_vocab.ADMIN,
                    User.is_active.is_(True),
                    User.id != user.id,
                )
            )
        ).scalar_one()
        if remaining == 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot remove the last active admin in the organization",
            )

    previous_role = user.role
    for field, value in changes.items():
        setattr(user, field, value)
    user.updated_at = datetime.now(timezone.utc)

    if "role" in changes and changes["role"] != previous_role:
        # In the SAME transaction as the change: an audit trail that can disagree
        # with the data is worse than no audit trail.
        await record_audit(
            action="user_role_changed",
            resource_type="user",
            resource_id=user.id,
            actor_id=current_user.id,
            organization_id=org_id,
            details={"previous_role": previous_role, "new_role": changes["role"]},
            session=db,
        )
    elif changes:
        await record_audit(
            action="user_updated",
            resource_type="user",
            resource_id=user.id,
            actor_id=current_user.id,
            organization_id=org_id,
            details={"fields": sorted(changes)},
            session=db,
        )

    await db.commit()

    if "role" in changes and changes["role"] != previous_role:
        # Role changes are the security-relevant edit, so they are logged
        # distinctly from an ordinary profile update.
        logger.warning(
            "user_role_changed",
            actor_id=str(current_user.id),
            user_id=str(user.id),
            organization_id=str(org_id),
            previous_role=previous_role,
            new_role=changes["role"],
        )
    else:
        logger.info(
            "user_updated",
            actor_id=str(current_user.id),
            user_id=str(user.id),
            fields=sorted(changes),
        )
    return user


@router.delete(
    "/{user_id}",
    response_model=UserAdminResponse,
    summary="Deactivate a user",
    description="Deactivate a user. Their history is preserved — accounts are never hard-deleted.",
)
async def deactivate_user(
    user_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db),
):
    user = await _own_org_user(db, user_id, org_id)

    if user.id == current_user.id:
        # Self-deactivation would log the caller out of an admin surface they may
        # be the only holder of, mid-request.
        raise HTTPException(status_code=409, detail="Cannot deactivate your own account")

    if user.role == role_vocab.ADMIN:
        remaining = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.organization_id == org_id,
                    User.role == role_vocab.ADMIN,
                    User.is_active.is_(True),
                    User.id != user.id,
                )
            )
        ).scalar_one()
        if remaining == 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot remove the last active admin in the organization",
            )

    # Deactivate rather than DELETE: alarms.acknowledged_by, alarm_rules.created_by
    # and task assignments reference this row. Removing it would either break those
    # references or erase who did what.
    user.is_active = False
    user.updated_at = datetime.now(timezone.utc)
    await record_audit(
        action="user_deactivated",
        resource_type="user",
        resource_id=user.id,
        actor_id=current_user.id,
        organization_id=org_id,
        details={"email": user.email, "role": user.role},
        session=db,
    )
    await db.commit()

    logger.warning(
        "user_deactivated",
        actor_id=str(current_user.id),
        user_id=str(user.id),
        organization_id=str(org_id),
    )
    return user
