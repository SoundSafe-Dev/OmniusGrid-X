"""Focused integration coverage for tenant user administration and invites."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg2
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.api.auth as auth_api
import app.api.users as users_api
from app.core.security import create_access_token
from app.db import database as db_module
from app.db.database import get_db
from app.middleware.rate_limit import (
    auth_limiter,
    rate_limit_exceeded_handler,
)
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
from slowapi.errors import RateLimitExceeded


@pytest.fixture
def user_management_rate_limiter():
    old_enabled = auth_limiter.enabled
    old_storage = auth_limiter._storage
    old_strategy = auth_limiter._limiter
    storage = MemoryStorage()
    auth_limiter._storage = storage
    auth_limiter._limiter = FixedWindowRateLimiter(storage)
    auth_limiter.enabled = True
    auth_limiter.reset()
    try:
        yield
    finally:
        auth_limiter.reset()
        auth_limiter.enabled = old_enabled
        auth_limiter._storage = old_storage
        auth_limiter._limiter = old_strategy


@pytest_asyncio.fixture
async def user_management_app(
    tenant_async_url,
    user_management_rate_limiter,
    monkeypatch,
):
    engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )
    original_session_maker = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = session_maker
    monkeypatch.setattr(
        users_api,
        "get_password_hash",
        lambda _password: "$2b$12$" + "y" * 53,
    )

    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_tenant_db(
        org_id: UUID = Depends(get_tenant_org_id),
    ):
        async with session_maker() as session:
            try:
                await session.execute(
                    text(
                        "SELECT set_config("
                        "'app.current_org_id', :org_id, false)"
                    ),
                    {"org_id": str(org_id)},
                )
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.execute(
                    text("SELECT set_config('app.current_org_id', '', false)")
                )
                await session.commit()

    application = FastAPI()
    application.state.auth_limiter = auth_limiter
    application.add_exception_handler(
        RateLimitExceeded,
        rate_limit_exceeded_handler,
    )
    application.include_router(
        auth_api.router,
        prefix="/api/v1/auth",
    )
    application.include_router(
        users_api.router,
        prefix="/api/v1/auth/users",
    )
    application.include_router(
        users_api.public_router,
        prefix="/api/v1/auth/invitations",
    )
    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_tenant_db] = override_tenant_db
    try:
        yield application, session_maker
    finally:
        application.dependency_overrides.clear()
        db_module.AsyncSessionLocal = original_session_maker
        await engine.dispose()


def _headers(jwt_for_user: dict, organization: str = "a") -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt_for_user[organization]}"}


@pytest.fixture
def captured_delivery(monkeypatch):
    deliveries: list[dict] = []

    async def deliver(invitation, *, token, organization_name):
        invitation.delivery_attempts += 1
        invitation.delivery_status = "sent"
        invitation.delivery_error_code = None
        invitation.delivered_at = datetime.now(timezone.utc)
        deliveries.append(
            {
                "token": token,
                "organization_name": organization_name,
                "invitation_id": invitation.id,
            }
        )
        return True

    monkeypatch.setattr(users_api, "deliver_invitation", deliver)
    return deliveries


@pytest.mark.asyncio
async def test_invite_accept_is_one_time_hashed_and_tenant_scoped(
    user_management_app,
    seeded_orgs,
    jwt_for_user,
    captured_delivery,
    admin_sync_url,
):
    application, _ = user_management_app
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/auth/users/invitations",
            headers=_headers(jwt_for_user),
            json={"email": "Invitee@Example.com", "role": "operator"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["email"] == "invitee@example.com"
        assert created.json()["deliveryStatus"] == "sent"
        token = captured_delivery[-1]["token"]

        cross_tenant = await client.post(
            f"/api/v1/auth/users/invitations/{created.json()['id']}/resend",
            headers=_headers(jwt_for_user, "b"),
        )
        assert cross_tenant.status_code == 404

        validated = await client.post(
            "/api/v1/auth/invitations/validate",
            json={"token": token},
        )
        assert validated.status_code == 200, validated.text
        assert validated.json()["organizationName"] == "Org A"
        assert validated.json()["role"] == "operator"

        accepted = await client.post(
            "/api/v1/auth/invitations/accept",
            json={
                "token": token,
                "name": "Invited User",
                "password": "a-secure-password",
            },
        )
        assert accepted.status_code == 201, accepted.text
        assert "access_token" not in accepted.text
        assert accepted.json()["user"]["organizationId"] == str(
            seeded_orgs["org_a_id"]
        )

        replay = await client.post(
            "/api/v1/auth/invitations/accept",
            json={
                "token": token,
                "name": "Replay",
                "password": "a-secure-password",
            },
        )
        assert replay.status_code == 410

        listed_a = await client.get(
            "/api/v1/auth/users",
            headers=_headers(jwt_for_user),
        )
        listed_b = await client.get(
            "/api/v1/auth/users",
            headers=_headers(jwt_for_user, "b"),
        )
        assert "invitee@example.com" in {
            user["email"] for user in listed_a.json()["items"]
        }
        assert "invitee@example.com" not in {
            user["email"] for user in listed_b.json()["items"]
        }

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT token_hash, status
                FROM user_invitations
                WHERE id = %s
                """,
                (created.json()["id"],),
            )
            stored_hash, invitation_status = cursor.fetchone()
            assert stored_hash != token
            assert token not in stored_hash
            assert len(stored_hash) == 64
            assert invitation_status == "accepted"
            cursor.execute(
                """
                SELECT details::text
                FROM audit_logs
                WHERE resource_id = %s
                """,
                (created.json()["id"],),
            )
            audit_text = "\n".join(row[0] for row in cursor.fetchall())
            assert token not in audit_text
            assert "#token=" not in audit_text
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_concurrent_accept_has_exactly_one_winner(
    user_management_app,
    jwt_for_user,
    captured_delivery,
):
    application, _ = user_management_app
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/v1/auth/users/invitations",
            headers=_headers(jwt_for_user),
            json={"email": f"race-{uuid4().hex}@example.com", "role": "viewer"},
        )
    assert created.status_code == 201
    token = captured_delivery[-1]["token"]

    async def accept(source_port: int):
        async with AsyncClient(
            transport=ASGITransport(
                app=application,
                client=("198.51.100.40", source_port),
            ),
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/v1/auth/invitations/accept",
                json={
                    "token": token,
                    "name": "Race Winner",
                    "password": "a-secure-password",
                },
            )

    responses = await asyncio.gather(accept(5001), accept(5002))
    assert sorted(response.status_code for response in responses) == [201, 410]


@pytest.mark.asyncio
async def test_role_change_and_deactivation_revoke_sessions_permanently(
    user_management_app,
    seeded_orgs,
    jwt_for_user,
    admin_sync_url,
):
    application, _ = user_management_app
    target_id = uuid4()
    refresh_jti = uuid4()
    session_id = uuid4()
    future = datetime.now(timezone.utc) + timedelta(days=1)
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (
                    id, email, hashed_password, full_name, organization_id,
                    role, is_active
                ) VALUES (%s, %s, %s, %s, %s, 'operator', true)
                """,
                (
                    str(target_id),
                    f"target-{target_id.hex[:8]}@example.com",
                    "$2b$12$" + "x" * 53,
                    "Target User",
                    str(seeded_orgs["org_a_id"]),
                ),
            )
            cursor.execute(
                """
                INSERT INTO user_sessions (
                    id, user_id, token_hash, jti, token_type, expires_at,
                    is_active
                ) VALUES (%s, %s, %s, %s, 'refresh', %s, true)
                """,
                (
                    str(session_id),
                    str(target_id),
                    "f" * 64,
                    str(refresh_jti),
                    future,
                ),
            )
    finally:
        conn.close()

    target_token = create_access_token(
        {
            "sub": str(target_id),
            "email": f"target-{target_id.hex[:8]}@example.com",
            "role": "operator",
            "sid": str(refresh_jti),
        }
    )
    target_headers = {"Authorization": f"Bearer {target_token}"}

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        before = await client.get("/api/v1/auth/me", headers=target_headers)
        assert before.status_code == 200

        changed = await client.patch(
            f"/api/v1/auth/users/{target_id}",
            headers=_headers(jwt_for_user),
            json={"role": "viewer"},
        )
        assert changed.status_code == 200, changed.text
        after_role_change = await client.get(
            "/api/v1/auth/me",
            headers=target_headers,
        )
        assert after_role_change.status_code == 401

        deactivated = await client.delete(
            f"/api/v1/auth/users/{target_id}",
            headers=_headers(jwt_for_user),
        )
        assert deactivated.status_code == 200
        reactivated = await client.post(
            f"/api/v1/auth/users/{target_id}/reactivate",
            headers=_headers(jwt_for_user),
        )
        assert reactivated.status_code == 200
        still_revoked = await client.get(
            "/api/v1/auth/me",
            headers=target_headers,
        )
        assert still_revoked.status_code == 401

        self_deactivate = await client.delete(
            f"/api/v1/auth/users/{seeded_orgs['user_a_id']}",
            headers=_headers(jwt_for_user),
        )
        assert self_deactivate.status_code == 409

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT action, details::text
                FROM audit_logs
                WHERE resource_id = %s
                """,
                (str(target_id),),
            )
            events = cursor.fetchall()
            actions = {row[0] for row in events}
            assert {
                "user_role_changed",
                "user_sessions_revoked",
                "user_deactivated",
                "user_reactivated",
            }.issubset(actions)
            assert target_token not in "\n".join(row[1] for row in events)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_non_admin_is_forbidden_and_cross_org_is_not_found(
    user_management_app,
    seeded_orgs,
    jwt_for_user,
    admin_sync_url,
):
    application, _ = user_management_app
    operator_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (
                    id, email, hashed_password, organization_id, role, is_active
                ) VALUES (%s, %s, %s, %s, 'operator', true)
                """,
                (
                    str(operator_id),
                    f"operator-{operator_id.hex[:8]}@example.com",
                    "$2b$12$" + "x" * 53,
                    str(seeded_orgs["org_a_id"]),
                ),
            )
    finally:
        conn.close()

    from app.core.config import settings
    from jose import jwt

    now = datetime.now(timezone.utc)
    operator_token = jwt.encode(
        {
            "sub": str(operator_id),
            "type": "access",
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        forbidden = await client.get(
            "/api/v1/auth/users",
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert forbidden.status_code == 403

        cross_org = await client.get(
            f"/api/v1/auth/users/{seeded_orgs['user_b_id']}",
            headers=_headers(jwt_for_user),
        )
        assert cross_org.status_code == 404
        assert cross_org.json() == {"detail": "User not found"}


@pytest.mark.asyncio
async def test_failed_delivery_resend_rotation_revoke_and_expiry(
    user_management_app,
    jwt_for_user,
    monkeypatch,
    admin_sync_url,
):
    application, _ = user_management_app
    delivered_tokens: list[str] = []

    async def changing_delivery(invitation, *, token, organization_name):
        del organization_name
        delivered_tokens.append(token)
        invitation.delivery_attempts += 1
        if len(delivered_tokens) == 1:
            invitation.delivery_status = "failed"
            invitation.delivery_error_code = "smtp_delivery_failed"
            return False
        invitation.delivery_status = "sent"
        invitation.delivery_error_code = None
        invitation.delivered_at = datetime.now(timezone.utc)
        return True

    monkeypatch.setattr(users_api, "deliver_invitation", changing_delivery)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/v1/auth/users/invitations",
            headers=_headers(jwt_for_user),
            json={
                "email": f"retry-{uuid4().hex}@example.com",
                "role": "viewer",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["deliveryStatus"] == "failed"
        invitation_id = created.json()["id"]
        first_token = delivered_tokens[-1]

        resent = await client.post(
            f"/api/v1/auth/users/invitations/{invitation_id}/resend",
            headers=_headers(jwt_for_user),
        )
        assert resent.status_code == 200, resent.text
        assert resent.json()["deliveryStatus"] == "sent"
        assert resent.json()["deliveryAttempts"] == 2
        second_token = delivered_tokens[-1]
        assert second_token != first_token

        old_link = await client.post(
            "/api/v1/auth/invitations/validate",
            json={"token": first_token},
        )
        new_link = await client.post(
            "/api/v1/auth/invitations/validate",
            json={"token": second_token},
        )
        assert old_link.status_code == 404
        assert new_link.status_code == 200

        revoked = await client.delete(
            f"/api/v1/auth/users/invitations/{invitation_id}",
            headers=_headers(jwt_for_user),
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        revoked_link = await client.post(
            "/api/v1/auth/invitations/validate",
            json={"token": second_token},
        )
        assert revoked_link.status_code == 410

        expiring = await client.post(
            "/api/v1/auth/users/invitations",
            headers=_headers(jwt_for_user),
            json={
                "email": f"expired-{uuid4().hex}@example.com",
                "role": "operator",
            },
        )
        assert expiring.status_code == 201
        expiring_token = delivered_tokens[-1]

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE user_invitations
                SET created_at = NOW() - INTERVAL '2 days',
                    expires_at = NOW() - INTERVAL '1 day'
                WHERE id = %s
                """,
                (expiring.json()["id"],),
            )
    finally:
        conn.close()

    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        expired = await client.post(
            "/api/v1/auth/invitations/validate",
            json={"token": expiring_token},
        )
        assert expired.status_code == 410

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM user_invitations WHERE id = %s",
                (expiring.json()["id"],),
            )
            assert cursor.fetchone()[0] == "expired"
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_concurrent_admin_changes_cannot_remove_every_admin(
    user_management_app,
    seeded_orgs,
    jwt_for_user,
    admin_sync_url,
):
    application, _ = user_management_app
    second_admin_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (
                    id, email, hashed_password, organization_id, role, is_active
                ) VALUES (%s, %s, %s, %s, 'admin', true)
                """,
                (
                    str(second_admin_id),
                    f"admin-{second_admin_id.hex[:8]}@example.com",
                    "$2b$12$" + "x" * 53,
                    str(seeded_orgs["org_a_id"]),
                ),
            )
    finally:
        conn.close()

    from app.core.config import settings
    from jose import jwt

    now = datetime.now(timezone.utc)
    second_admin_token = jwt.encode(
        {
            "sub": str(second_admin_id),
            "type": "access",
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    async def demote(
        actor_token: str,
        target_id: UUID,
        source_port: int,
    ):
        async with AsyncClient(
            transport=ASGITransport(
                app=application,
                client=("198.51.100.55", source_port),
            ),
            base_url="http://test",
        ) as client:
            return await client.patch(
                f"/api/v1/auth/users/{target_id}",
                headers={"Authorization": f"Bearer {actor_token}"},
                json={"role": "operator"},
            )

    responses = await asyncio.gather(
        demote(jwt_for_user["a"], second_admin_id, 5101),
        demote(
            second_admin_token,
            seeded_orgs["user_a_id"],
            5102,
        ),
    )
    status_codes = [response.status_code for response in responses]
    assert status_codes.count(200) == 1
    assert next(code for code in status_codes if code != 200) in {403, 409}

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM users
                WHERE organization_id = %s
                  AND role = 'admin'
                  AND is_active = true
                """,
                (str(seeded_orgs["org_a_id"]),),
            )
            assert cursor.fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_public_registration_is_disabled(
    user_management_app,
    seeded_orgs,
):
    application, _ = user_management_app
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"open-{uuid4().hex}@example.com",
                "password": "a-secure-password",
                "full_name": "Open Registration",
                "organization_id": str(seeded_orgs["org_a_id"]),
            },
        )
    assert response.status_code == 403
    assert response.json() == {
        "detail": (
            "Open registration is disabled; users are provisioned by an "
            "administrator."
        )
    }


def test_invitation_migration_is_idempotent_and_forces_rls(admin_sync_url):
    import sqlparse

    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "049_user_invitations.sql"
    ).read_text()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cursor:
            for statement in sqlparse.split(sql):
                if statement.strip():
                    cursor.execute(statement)
            cursor.execute(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE relname = 'user_invitations'
                """
            )
            assert cursor.fetchone() == (True, True)
    finally:
        conn.close()
