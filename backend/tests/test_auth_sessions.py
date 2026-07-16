import asyncio
from datetime import datetime, timedelta, timezone

import psycopg2
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter

import app.api.auth as auth_api
from app.core.security import decode_local_token
from app.core.session import SessionManager
from app.db import database as db_module
from app.db.database import get_db
from app.middleware.rate_limit import (
    auth_limiter,
    limiter,
    rate_limit_exceeded_handler,
)
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
def auth_memory_limiter():
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
async def auth_app(tenant_async_url):
    engine = create_async_engine(tenant_async_url, future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
    )
    original_session_maker = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = session_maker

    async def override_get_db():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application = FastAPI()
    application.state.auth_limiter = auth_limiter
    application.add_exception_handler(
        RateLimitExceeded,
        rate_limit_exceeded_handler,
    )
    application.include_router(auth_api.router, prefix="/api/v1/auth")
    application.dependency_overrides[get_db] = override_get_db
    try:
        yield application
    finally:
        application.dependency_overrides.clear()
        db_module.AsyncSessionLocal = original_session_maker
        await engine.dispose()


def _email_for(seeded_orgs: dict) -> str:
    return f"a-{seeded_orgs['user_a_id'].hex[:8]}@test.local"


async def _login(client: AsyncClient, seeded_orgs: dict):
    return await client.post(
        "/api/v1/auth/login",
        data={
            "username": _email_for(seeded_orgs),
            "password": "test-password",
        },
    )


@pytest.mark.asyncio
async def test_refresh_rotation_and_logout_are_database_durable(
    auth_app,
    seeded_orgs,
    admin_sync_url,
    monkeypatch,
    auth_memory_limiter,
):
    monkeypatch.setattr(auth_api, "verify_password", lambda *_: True)
    transport = ASGITransport(app=auth_app, client=("198.51.100.20", 4000))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await _login(client, seeded_orgs)
        assert login.status_code == 200, login.text
        first_pair = login.json()

        first_access = decode_local_token(
            first_pair["access_token"],
            expected_type="access",
        )
        first_refresh = decode_local_token(
            first_pair["refresh_token"],
            expected_type="refresh",
        )
        assert first_access["jti"] != first_refresh["jti"]
        assert first_access["sid"] == first_refresh["jti"]

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT token_hash, jti, expires_at, metadata::text
                    FROM user_sessions
                    WHERE user_id = %s
                    """,
                    (str(seeded_orgs["user_a_id"]),),
                )
                token_hash, stored_jti, expires_at, metadata = cur.fetchone()
        finally:
            conn.close()

        assert token_hash == SessionManager.hash_token(first_pair["refresh_token"])
        assert str(stored_jti) == first_refresh["jti"]
        assert first_pair["refresh_token"] not in token_hash
        assert first_pair["refresh_token"] not in metadata
        remaining = expires_at - datetime.now(timezone.utc)
        assert timedelta(days=6, hours=23) < remaining <= timedelta(days=7)

        rotated = await client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": first_pair["refresh_token"]},
        )
        assert rotated.status_code == 200, rotated.text
        second_pair = rotated.json()

        replay = await client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": first_pair["refresh_token"]},
        )
        assert replay.status_code == 401
        assert replay.json() == {"detail": "Invalid refresh token"}

        current = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {second_pair['access_token']}"},
        )
        assert current.status_code == 200

        logout_headers = {
            "Authorization": f"Bearer {second_pair['access_token']}"
        }
        logout_body = {"refreshToken": second_pair["refresh_token"]}
        first_logout = await client.post(
            "/api/v1/auth/logout",
            json=logout_body,
            headers=logout_headers,
        )
        repeated_logout = await client.post(
            "/api/v1/auth/logout",
            json=logout_body,
            headers=logout_headers,
        )
        assert first_logout.status_code == 200
        assert repeated_logout.status_code == 200

        revoked_access = await client.get(
            "/api/v1/auth/me",
            headers=logout_headers,
        )
        revoked_refresh = await client.post(
            "/api/v1/auth/refresh",
            json=logout_body,
        )
        assert revoked_access.status_code == 401
        assert revoked_refresh.status_code == 401

    # A brand-new database session sees both revocations. No process-local
    # state is needed, so another replica or a restarted backend behaves alike.
    second_access = decode_local_token(
        second_pair["access_token"],
        expected_type="access",
    )
    second_refresh = decode_local_token(
        second_pair["refresh_token"],
        expected_type="refresh",
    )
    async with db_module.AsyncSessionLocal() as db:
        assert await SessionManager.is_token_revoked(second_access["jti"], db)
        assert await SessionManager.is_token_revoked(second_refresh["jti"], db)

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_sessions SET expires_at = NOW() - INTERVAL '1 second' "
                "WHERE user_id = %s",
                (str(seeded_orgs["user_a_id"]),),
            )
            cur.execute(
                "UPDATE revoked_tokens SET expires_at = NOW() - INTERVAL '1 second' "
                "WHERE user_id = %s",
                (str(seeded_orgs["user_a_id"]),),
            )
    finally:
        conn.close()

    async with db_module.AsyncSessionLocal() as db:
        assert await SessionManager.cleanup_expired_sessions(db) >= 2
        await db.commit()


@pytest.mark.asyncio
async def test_concurrent_refresh_allows_exactly_one_rotation(
    auth_app,
    seeded_orgs,
    admin_sync_url,
    monkeypatch,
    auth_memory_limiter,
):
    monkeypatch.setattr(auth_api, "verify_password", lambda *_: True)
    login_transport = ASGITransport(
        app=auth_app,
        client=("198.51.100.21", 4001),
    )
    async with AsyncClient(
        transport=login_transport,
        base_url="http://test",
    ) as client:
        login = await _login(client, seeded_orgs)
    assert login.status_code == 200
    old_refresh = login.json()["refresh_token"]

    async def rotate(source_port: int):
        transport = ASGITransport(
            app=auth_app,
            client=("198.51.100.22", source_port),
        )
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(
                "/api/v1/auth/refresh",
                json={"refreshToken": old_refresh},
            )

    responses = await asyncio.gather(rotate(4101), rotate(4102))
    assert sorted(response.status_code for response in responses) == [200, 401]

    winner = next(response.json() for response in responses if response.status_code == 200)
    winner_refresh = decode_local_token(
        winner["refresh_token"],
        expected_type="refresh",
    )

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*), min(jti::text)
                FROM user_sessions
                WHERE user_id = %s AND is_active = true
                """,
                (str(seeded_orgs["user_a_id"]),),
            )
            active_count, active_jti = cur.fetchone()
    finally:
        conn.close()

    assert active_count == 1
    assert active_jti == winner_refresh["jti"]


@pytest.mark.asyncio
async def test_login_is_throttled_with_global_rate_limiting_off(
    auth_app,
    seeded_orgs,
    auth_memory_limiter,
):
    old_global_enabled = limiter.enabled
    limiter.enabled = False
    try:
        transport = ASGITransport(
            app=auth_app,
            client=("198.51.100.23", 4200),
        )
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            responses = [
                await client.post(
                    "/api/v1/auth/login",
                    data={
                        "username": "missing-user@test.local",
                        "password": "wrong",
                    },
                )
                for _ in range(11)
            ]
    finally:
        limiter.enabled = old_global_enabled

    assert [response.status_code for response in responses[:10]] == [401] * 10
    assert responses[10].status_code == 429


@pytest.mark.asyncio
async def test_register_and_refresh_have_independent_auth_budgets(
    auth_app,
    seeded_orgs,
    auth_memory_limiter,
):
    transport = ASGITransport(
        app=auth_app,
        client=("198.51.100.24", 4300),
    )
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        register_responses = [
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": _email_for(seeded_orgs),
                    "password": "not-used",
                },
            )
            for _ in range(6)
        ]
        refresh_responses = [
            await client.post(
                "/api/v1/auth/refresh",
                json={"refreshToken": "not-a-jwt"},
            )
            for _ in range(31)
        ]

    assert [response.status_code for response in register_responses[:5]] == [400] * 5
    assert register_responses[5].status_code == 429
    assert [response.status_code for response in refresh_responses[:30]] == [401] * 30
    assert refresh_responses[30].status_code == 429
