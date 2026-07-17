"""Focused tests for the shared role dependencies."""

import ast
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api import auth as auth_api
from app.db.models import APIKey, Base
from app.middleware.rbac import (
    require_admin,
    require_operator_or_admin,
    require_roles,
)


def _user(role: str, *, is_active: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        role=role,
        is_active=is_active,
    )


@pytest.mark.asyncio
async def test_require_admin_allows_admin():
    user = _user("admin")
    assert await require_admin(current_user=user) is user


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "viewer"])
async def test_require_admin_rejects_non_admin(role):
    with pytest.raises(HTTPException) as exc_info:
        await require_admin(current_user=_user(role))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin role required"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "operator"])
async def test_operator_dependency_allows_mutating_roles(role):
    user = _user(role)
    assert await require_operator_or_admin(current_user=user) is user


@pytest.mark.asyncio
async def test_operator_dependency_rejects_viewer():
    with pytest.raises(HTTPException) as exc_info:
        await require_operator_or_admin(current_user=_user("viewer"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Operator or admin role required"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "viewer"])
async def test_require_roles_allows_explicit_roles(role):
    dependency = require_roles("admin", "viewer")
    user = _user(role)
    assert await dependency(current_user=user) is user


@pytest.mark.asyncio
async def test_require_roles_rejects_unlisted_role():
    dependency = require_roles("admin", "viewer")
    with pytest.raises(HTTPException) as exc_info:
        await dependency(current_user=_user("operator"))

    assert exc_info.value.status_code == 403


def test_require_roles_requires_at_least_one_role():
    with pytest.raises(ValueError, match="At least one allowed role"):
        require_roles()


@pytest.mark.asyncio
async def test_missing_user_is_rejected_by_auth_dependency():
    with pytest.raises(HTTPException) as exc_info:
        await auth_api.get_current_active_user(
            token=None,
            header_token=None,
            db=None,
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_inactive_user_is_rejected_before_role_dependency(monkeypatch):
    async def _inactive_user(_token, _db):
        return _user("admin", is_active=False)

    monkeypatch.setattr(auth_api, "get_current_user", _inactive_user)
    monkeypatch.setattr(auth_api.settings, "KEYCLOAK_ENABLED", False)

    with pytest.raises(HTTPException) as exc_info:
        await auth_api.get_current_active_user(
            token="test-token",
            header_token=None,
            db=None,
        )

    # Converged behavior: an inactive/unresolvable user folds into a generic
    # 401 (non-leaky — doesn't reveal the account exists but is disabled),
    # matching the login endpoint's "Incorrect email or password" stance.
    # The point of this test stands: rejection happens before any role
    # dependency ever runs.
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Could not validate credentials"


def test_rbac_has_one_admin_dependency_and_no_dead_permission_runtime():
    app_root = Path(__file__).resolve().parents[1] / "app"
    definitions = []
    admin_helper_names = {
        "require_admin",
        "require_admin_user",
        "require_export_admin",
    }
    dead_names = {
        "Permission",
        "RolePermission",
        "RBACMiddleware",
        "require_permission",
        "require_any_permission",
    }
    referenced_dead_names = set()

    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        definitions.extend(
            (path.relative_to(app_root), node.name)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in admin_helper_names
        )
        referenced_dead_names.update(
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id in dead_names
        )

    assert definitions == [(Path("middleware/rbac.py"), "require_admin")]
    assert not referenced_dead_names


def test_permission_models_are_removed_but_api_key_scopes_remain():
    assert "permissions" not in Base.metadata.tables
    assert "role_permissions" not in Base.metadata.tables
    assert "scopes" in APIKey.__table__.c


def test_permission_cleanup_migration_drops_children_before_parent():
    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "037_remove_unused_permission_rbac.sql"
    ).read_text()

    child_drop = migration.index("DROP TABLE IF EXISTS role_permissions")
    parent_drop = migration.index("DROP TABLE IF EXISTS permissions")
    assert child_drop < parent_drop
