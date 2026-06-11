"""Pytest fixtures for tenant-isolation integration tests.

Strategy
--------
1. Spin up an ephemeral TimescaleDB container (Docker, via testcontainers).
2. Build the schema from ``app.db.models`` (matching what ``init_db``
   does in dev/prod), install the real audit trigger, and apply the RLS migrations.
3. Create a non-superuser role ``tenant_user`` and grant it the
   privileges the app would have in production. Critical because
   superusers bypass RLS even with FORCE.
4. Re-bind the FastAPI app to a SQLAlchemy engine that connects as
   ``tenant_user``. Override ``get_db`` / ``get_tenant_db`` so the
   production code path runs against the test DB.
5. Seed two organizations and two users (one per org), issue JWTs, and
   yield authenticated HTTP clients.

Everything lives inside the temporary container. When the test session
ends, the container is destroyed and all data with it.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "database" / "migrations"

# Setting a placeholder DATABASE_URL here keeps ``app.core.config`` happy
# when modules are imported during collection. The real URL is wired in
# via ``app.dependency_overrides`` once the container is up.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://placeholder:placeholder@localhost/placeholder"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_schema(sync_url: str) -> None:
    """Create the test schema and apply RLS migrations.

    Schema is built from ``app.db.models.Base.metadata`` — the same
    source ``init_db`` uses in dev/prod. The audit and RLS migrations
    are applied on top in order.
    """
    import psycopg2
    import sqlparse
    from sqlalchemy import create_engine

    from app.db.models import Base

    sync_engine = create_engine(sync_url)
    try:
        Base.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()

    migration_files = [
        "009_audit_logs.sql",
        "011_tenant_isolation_rls.sql",
        "012_export_templates.sql",
        "014_compliance_tenant_isolation.sql",
        "015_compliance_report_jobs.sql",
        "016_finalize_compliance_tenant_ownership.sql",
    ]

    conn = psycopg2.connect(sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = 'omniusgrid_app'
                    ) THEN
                        CREATE ROLE omniusgrid_app NOLOGIN;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = 'omniusgrid_readonly'
                    ) THEN
                        CREATE ROLE omniusgrid_readonly NOLOGIN;
                    END IF;
                END
                $$;
                """
            )
            for migration_name in migration_files:
                migration_path = MIGRATIONS_DIR / migration_name
                sql = migration_path.read_text()
                statements = []
                for raw in sqlparse.split(sql):
                    if not sqlparse.format(raw, strip_comments=True).strip():
                        continue
                    statements.append(raw.strip())

                for stmt in statements:
                    try:
                        cur.execute(stmt)
                    except Exception as exc:  # noqa: BLE001
                        raise RuntimeError(
                            f"{migration_name} failed on statement:\n"
                            f"{stmt[:200]}{'...' if len(stmt) > 200 else ''}\n"
                            f"Error: {exc}"
                        ) from exc
    finally:
        conn.close()


def _provision_tenant_role(sync_url: str, role: str, password: str) -> None:
    """Create a non-superuser role with privileges the app would have in prod.

    Critically, this role is NOT a superuser and does NOT own the tables
    (the container's POSTGRES_USER does). That combination is what makes
    RLS actually apply to its sessions.
    """
    import psycopg2

    conn = psycopg2.connect(sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"DO $$ BEGIN "
                f"  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN "
                f"    CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOBYPASSRLS; "
                f"  END IF; "
                f"END $$;"
            )
            cur.execute(f"GRANT USAGE ON SCHEMA public TO {role};")
            cur.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE "
                f"ON ALL TABLES IN SCHEMA public TO {role};"
            )
            cur.execute(
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role};"
            )
            cur.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role};"
            )
    finally:
        conn.close()


def _build_async_url(sync_url: str, user: str, password: str) -> str:
    """Build an asyncpg URL using a specific user/password against the same host/db."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(sync_url)
    host = parts.hostname or "localhost"
    port = parts.port
    netloc = f"{user}:{password}@{host}"
    if port:
        netloc = f"{netloc}:{port}"
    return urlunsplit(("postgresql+asyncpg", netloc, parts.path, "", ""))


def _hash_password(plain: str) -> str:
    """Return a placeholder bcrypt-format hash for seeded users.

    The tenant-isolation tests authenticate by minting JWTs directly
    (see ``_make_jwt``); no test ever calls ``verify()`` against this
    value. We therefore return a syntactically valid bcrypt hash string
    rather than running a real key-derivation, which avoids a brittle
    passlib/bcrypt version dependency and keeps fixtures fast.
    """
    return "$2b$12$" + "x" * 53


def _make_jwt(user_id: UUID, secret: str, algorithm: str = "HS256") -> str:
    """Mint a JWT the auth dependency will accept."""
    from jose import jwt

    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_container():
    """Start an ephemeral TimescaleDB container for the whole test session."""
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer(
        image="timescale/timescaledb:latest-pg15",
        username="omniusgrid",
        password="omniusgrid_dev_password",
        dbname="omniusgrid_test",
    )
    container.start()
    try:
        # ``testcontainers`` returns a SQLAlchemy-style URL
        # (``postgresql+psycopg2://...``). Raw ``psycopg2.connect()`` does
        # not accept the ``+psycopg2`` driver suffix, so we normalize to a
        # plain ``postgresql://`` URL before handing it to migration /
        # seeding helpers and downstream fixtures.
        sync_url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql://"
        )
        _setup_schema(sync_url)
        _provision_tenant_role(sync_url, "tenant_user", "tenant_pass")
        yield container, sync_url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def admin_sync_url(pg_container) -> str:
    """Synchronous superuser URL — used for setup/inspection only."""
    _, sync_url = pg_container
    return sync_url


@pytest.fixture(scope="session")
def tenant_async_url(pg_container) -> str:
    """Async URL connecting as the non-superuser ``tenant_user``."""
    _, sync_url = pg_container
    return _build_async_url(sync_url, "tenant_user", "tenant_pass")


@pytest_asyncio.fixture
async def app(tenant_async_url):
    """The FastAPI app rebound to the test database.

    Function-scoped on purpose: ``pytest-asyncio`` runs each test in its
    own event loop, and an asyncpg engine is bound to the loop that
    created it. A session-scoped engine would raise "attached to a
    different loop" on the second test. The container itself stays
    session-scoped (it's synchronous), so only the cheap async engine is
    rebuilt per test.

    We override ``get_db`` and ``get_tenant_db`` so endpoints execute
    against the ephemeral container instead of the engine that
    ``app.db.database`` created at import time pointing at a placeholder.
    """
    from fastapi import Depends
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db import database as db_module
    from app.main import app as fastapi_app
    from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
    import app.api.compliance_reports as compliance_reports_api
    import app.api.exports as exports_api
    import app.services.report_download_audit as report_download_audit

    test_engine = create_async_engine(tenant_async_url, future=True)
    test_session_maker = async_sessionmaker(
        test_engine, expire_on_commit=False, autoflush=False
    )
    original_async_session_local = db_module.AsyncSessionLocal
    db_module.AsyncSessionLocal = test_session_maker
    compliance_reports_api.AsyncSessionLocal = test_session_maker
    exports_api.AsyncSessionLocal = test_session_maker
    report_download_audit.AsyncSessionLocal = test_session_maker

    async def _override_get_db() -> AsyncIterator:
        async with test_session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def _override_get_tenant_db(
        org_id: UUID = Depends(get_tenant_org_id),
    ) -> AsyncIterator:
        # Mirrors the production get_tenant_db: session-scoped GUC so it
        # survives mid-request commits (create/update + refresh), reset at
        # the end so context can't leak to a connection reused by a later
        # request.
        async with test_session_maker() as session:
            try:
                await session.execute(
                    text("SELECT set_config('app.current_org_id', :org_id, false)"),
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
                await session.close()

    # FastAPI's dependency-override matches on the original callable.
    # Each override keeps its own ``Depends`` chain so ``get_tenant_org_id``
    # is still resolved against the live JWT and User dependencies.
    fastapi_app.dependency_overrides[db_module.get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_tenant_db] = _override_get_tenant_db

    yield fastapi_app

    fastapi_app.dependency_overrides.clear()
    db_module.AsyncSessionLocal = original_async_session_local
    compliance_reports_api.AsyncSessionLocal = original_async_session_local
    exports_api.AsyncSessionLocal = original_async_session_local
    report_download_audit.AsyncSessionLocal = original_async_session_local
    await test_engine.dispose()


# ---------------------------------------------------------------------------
# Function-scoped fixtures: orgs, users, clients
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seeded_orgs(admin_sync_url) -> dict:
    """Create two orgs and two users (one per org). Returns a structured dict.

    Uses a synchronous superuser connection so the seed itself isn't
    subject to RLS. Returns plain Python types so tests can compose
    independently.
    """
    import psycopg2

    org_a_id = uuid4()
    org_b_id = uuid4()
    user_a_id = uuid4()
    user_b_id = uuid4()
    workcell_a_id = uuid4()
    workcell_b_id = uuid4()
    pw_hash = _hash_password("test-password")

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (id, name, slug) VALUES "
                "(%s, %s, %s), (%s, %s, %s);",
                (
                    str(org_a_id), "Org A", f"org-a-{org_a_id.hex[:8]}",
                    str(org_b_id), "Org B", f"org-b-{org_b_id.hex[:8]}",
                ),
            )
            cur.execute(
                "INSERT INTO users "
                "(id, email, hashed_password, organization_id, role, is_active) VALUES "
                "(%s, %s, %s, %s, 'admin', %s), "
                "(%s, %s, %s, %s, 'admin', %s);",
                (
                    str(user_a_id), f"a-{user_a_id.hex[:8]}@test.local",
                    pw_hash, str(org_a_id), True,
                    str(user_b_id), f"b-{user_b_id.hex[:8]}@test.local",
                    pw_hash, str(org_b_id), True,
                ),
            )
            # assets.workcell_id is NOT NULL, so every org needs a workcell
            # before an asset can be created (via API or direct insert).
            cur.execute(
                "INSERT INTO workcells (id, organization_id, name) VALUES "
                "(%s, %s, %s), (%s, %s, %s);",
                (
                    str(workcell_a_id), str(org_a_id), "Workcell A",
                    str(workcell_b_id), str(org_b_id), "Workcell B",
                ),
            )
    finally:
        conn.close()

    return {
        "org_a_id": org_a_id,
        "org_b_id": org_b_id,
        "user_a_id": user_a_id,
        "user_b_id": user_b_id,
        "workcell_a_id": workcell_a_id,
        "workcell_b_id": workcell_b_id,
    }


@pytest.fixture
def jwt_for_user(seeded_orgs) -> dict:
    """Return JWT bearer tokens for both seeded users."""
    from app.core.config import settings

    return {
        "a": _make_jwt(seeded_orgs["user_a_id"], settings.JWT_SECRET_KEY,
                       settings.JWT_ALGORITHM),
        "b": _make_jwt(seeded_orgs["user_b_id"], settings.JWT_SECRET_KEY,
                       settings.JWT_ALGORITHM),
    }


@pytest_asyncio.fixture
async def client_a(app, jwt_for_user):
    """Authenticated HTTP client for the user in Org A."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {jwt_for_user['a']}"},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def client_b(app, jwt_for_user):
    """Authenticated HTTP client for the user in Org B."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {jwt_for_user['b']}"},
    ) as client:
        yield client
