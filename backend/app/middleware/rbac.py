"""Shared role-based access dependencies."""

from collections.abc import Callable

import structlog
from fastapi import Depends, HTTPException, status

from app.api.auth import get_current_active_user
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
    if current_user.role != "admin":
        _deny(current_user, "Admin role required", {"admin"})
    return current_user


async def require_operator_or_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Return the active user when they may perform operational mutations."""
    allowed_roles = {"admin", "operator"}
    if current_user.role not in allowed_roles:
        _deny(current_user, "Operator or admin role required", allowed_roles)
    return current_user


def require_roles(*allowed_roles: str) -> Callable[..., User]:
    """Build a FastAPI dependency for an explicit set of application roles."""
    allowed = set(allowed_roles)
    if not allowed:
        raise ValueError("At least one allowed role is required")

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
