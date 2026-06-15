"""Focused unit tests for role decorators."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.middleware.rbac import require_admin, require_roles


def _user(role: str):
    return SimpleNamespace(id=uuid4(), role=role)


@pytest.mark.asyncio
async def test_require_admin_allows_admin():
    @require_admin()
    async def endpoint(*, current_user):
        return current_user.role

    assert await endpoint(current_user=_user("admin")) == "admin"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "viewer"])
async def test_require_admin_rejects_non_admin(role):
    @require_admin()
    async def endpoint(*, current_user):
        return current_user.role

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(current_user=_user(role))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin role required"


@pytest.mark.asyncio
async def test_require_admin_rejects_missing_user():
    @require_admin()
    async def endpoint():
        return "unreachable"

    with pytest.raises(HTTPException) as exc_info:
        await endpoint()

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "viewer"])
async def test_require_roles_allows_explicit_roles(role):
    @require_roles("admin", "viewer")
    async def endpoint(*, current_user):
        return current_user.role

    assert await endpoint(current_user=_user(role)) == role


@pytest.mark.asyncio
async def test_require_roles_rejects_unlisted_role():
    @require_roles("admin", "viewer")
    async def endpoint(*, current_user):
        return current_user.role

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(current_user=_user("operator"))

    assert exc_info.value.status_code == 403


def test_require_roles_requires_at_least_one_role():
    with pytest.raises(ValueError, match="At least one allowed role"):
        require_roles()
