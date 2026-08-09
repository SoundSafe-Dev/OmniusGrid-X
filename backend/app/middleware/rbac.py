"""Shared role-based access dependencies.

The role vocabulary and its ORDERING live in app/core/roles.py. Nothing here
hard-codes a role string any more: this module previously carried "admin" and
{"admin", "operator"} inline while sso.py kept its own frozenset and
compliance_reports.py its own tuple, and those three had already drifted.
"""

from collections.abc import Callable

import structlog
from fastapi import Depends, HTTPException, status

from app.api.auth import get_current_active_user
from app.core import roles as role_vocab
from app.db.models import User

logger = structlog.get_logger()


def _deny(current_user: User, detail: str, allowed_roles: set[str]) -> None:
    logger.warning(
        "role_access_denied",
        user_id=str(current_user.id),
        user_role=current_user.role,
        allowed_roles=sorted(allowed_roles),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


async def require_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Return the active user when they have the admin role."""
    if current_user.role != role_vocab.ADMIN:
        _deny(current_user, "Admin role required", {role_vocab.ADMIN})
    return current_user


async def require_operator_or_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Return the active user when they may perform operational mutations."""
    allowed_roles = set(role_vocab.roles_at_least(role_vocab.OPERATOR))
    if current_user.role not in allowed_roles:
        _deny(current_user, "Operator or admin role required", allowed_roles)
    return current_user


def require_roles(*allowed_roles: str) -> Callable[..., User]:
    """Build a FastAPI dependency for an explicit set of application roles.

    Unknown role names raise at import time rather than producing a dependency
    that silently rejects everyone — the failure mode this codebase already hit
    with an unconstrained `users.role` column.
    """
    allowed = set(allowed_roles)
    if not allowed:
        raise ValueError("At least one allowed role is required")
    unknown = allowed - role_vocab.ROLES
    if unknown:
        raise ValueError(
            f"unknown role(s) {sorted(unknown)}; known roles are "
            f"{sorted(role_vocab.ROLES)}"
        )

    async def role_dependency(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in allowed:
            _deny(
                current_user,
                f"One of roles {sorted(allowed)} required",
                allowed,
            )
        return current_user

    return role_dependency


def require_at_least(minimum: str) -> Callable[..., User]:
    """Build a dependency for "``minimum`` or more privileged".

    Prefer this over :func:`require_roles` when the intent is a floor rather than
    an exact set. `require_roles('admin', 'viewer')` on two read-only
    compliance-report endpoints DENIED `operator` — the default role every
    registered user gets — because an enumerated set has no notion of ordering.
    `require_at_least(VIEWER)` cannot express that inversion.
    """
    allowed = role_vocab.roles_at_least(minimum)

    async def role_dependency(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in allowed:
            _deny(current_user, f"Role {minimum} or higher required", set(allowed))
        return current_user

    return role_dependency
