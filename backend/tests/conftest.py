"""Pytest fixtures for tenant-isolation integration tests.

Strategy
--------
1. Spin up an ephemeral TimescaleDB container (Docker, via testcontainers).
2. Build the schema from the REAL migration chain (scripts/migrate.py over
   database/migrations/*.sql) — the same path production uses (FS-57).
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
import socket
import sys
import tarfile
import time
from io import BytesIO
from textwrap import dedent
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
    """Build the test schema from the REAL migration chain (FS-57).

    Previously this used ``Base.metadata.create_all`` plus a hand-picked
    11-migration overlay — a third schema-build path that diverged from both
    dev (sqlite create_all) and prod (full migrations). Tests now exercise
    exactly what production runs: scripts/migrate.py over
    database/migrations/*.sql. Migrations 002/005 need timescaledb (the
    container image provides it).
    """
    import subprocess
    import time

    import psycopg2

    # The timescaledb entrypoint restarts postgres after init; testcontainers'
    # readiness check can pass against the temp server, so retry the first
    # real connection instead of racing it.
    last_exc = None
    for _ in range(30):
        try:
            conn = psycopg2.connect(sync_url)
            break
        except psycopg2.OperationalError as exc:
            last_exc = exc
            time.sleep(2)
    else:
        raise RuntimeError(f"test postgres never became reachable: {last_exc}")

    # Roles some migrations grant to (optional least-privilege roles in real
    # deployments; the runner's guards skip them when absent, but creating
    # them here exercises the grant paths too). The full migrate.py chain below
    # (which now includes the renumbered 034..038 integration migrations) builds
    # every table, so the old create_all + hand-picked overlay is not needed.
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'omniusgrid_app') THEN
                        CREATE ROLE omniusgrid_app NOLOGIN;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'omniusgrid_readonly') THEN
                        CREATE ROLE omniusgrid_readonly NOLOGIN;
                    END IF;
                END
                $$;
                """
            )
    finally:
        conn.close()

    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "migrate.py")],
        env={**os.environ, "DATABASE_URL": sync_url},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"migration chain failed building the test schema:\n"
            f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )



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
    import jwt

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_container():
    """Start an ephemeral TimescaleDB container for the whole test session."""
    from testcontainers.postgres import PostgresContainer

    # testcontainers 4.x renamed the `user` kwarg to `username` (it raises
    # ValueError on the old spelling); `dbname` and get_connection_url() are
    # unchanged.
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
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db import database as db_module
    from app.main import app as fastapi_app
    from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
    # These look unused but are load-bearing: they guarantee the modules are in
    # sys.modules before the AsyncSessionLocal sweep below runs. Importing
    # app.main pulls in the mounted routers, but these are reached lazily in
    # places, so keep the explicit imports. noqa: F401 — do not "clean up".
    import app.api.agent_releases as agent_releases_api  # noqa: F401
    import app.api.models as models_api  # noqa: F401
    import app.services.rollout_orchestrator as rollout_orchestrator_service  # noqa: F401
    import app.api.compliance_reports as compliance_reports_api  # noqa: F401
    import app.api.erp_integrations as erp_integrations_api  # noqa: F401
    import app.api.exports as exports_api  # noqa: F401
    import app.services.report_download_audit as report_download_audit  # noqa: F401
    import app.api.notifications  # noqa: F401
    import app.api.edge_fleet  # noqa: F401
    import app.api.oee  # noqa: F401
    import app.api.commands  # noqa: F401
    import app.api.kanban  # noqa: F401

    test_engine = create_async_engine(tenant_async_url, future=True)
    test_session_maker = async_sessionmaker(
        test_engine, expire_on_commit=False, autoflush=False
    )

    # Modules do `from app.db.database import AsyncSessionLocal`, so each binds
    # its own reference at import time and patching app.db.database alone never
    # reaches them. This used to patch a hardcoded list of 8 modules while 41
    # bind the name, so anything newer (notifications, edge_fleet, oee, kanban,
    # commands, …) still pointed at the placeholder DATABASE_URL set at the top
    # of this file — surfacing as `role "placeholder" does not exist` 500s in the
    # real-DB smoke rather than as a missing fixture. The teardown also restored
    # only 7 of the 8. Sweeping sys.modules keeps both directions complete and
    # self-maintaining as routers are added.
    patched_modules = [
        module
        for name, module in list(sys.modules.items())
        if name.startswith("app.")
        and getattr(module, "AsyncSessionLocal", None) is not None
    ]
    original_session_locals = {
        module: module.AsyncSessionLocal for module in patched_modules
    }
    for module in patched_modules:
        module.AsyncSessionLocal = test_session_maker

    # `engine` NEEDS THE SAME SWEEP, and did not have it. The comment above says this is kept
    # "complete and self-maintaining", and it swept one of the two names `app.db.database`
    # exports: six modules bind `engine`, including `app.db.database` itself and
    # `app.api.health`, whose `_vacuum_telemetry` opens a connection on it directly.
    #
    # The consequence was invisible because nothing reached that handler. A walk over the POST
    # surface did, and got `role "placeholder" does not exist` — the exact error this sweep
    # exists to prevent, from the exact cause, one attribute over.
    patched_engines = [
        module
        for name, module in list(sys.modules.items())
        if name.startswith("app.") and getattr(module, "engine", None) is not None
    ]
    original_engines = {module: module.engine for module in patched_engines}
    for module in patched_engines:
        module.engine = test_engine
    original_async_session_local = original_session_locals.get(
        db_module, db_module.AsyncSessionLocal
    )

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
        # DELEGATES to the production implementation, swapping only the session
        # maker. It must not reimplement it.
        #
        # This used to be a hand-copy of `get_tenant_db`'s body, under a comment
        # reading "Mirrors the production get_tenant_db." It mirrored the bug
        # too: both set the GUC once with `set_config(..., false)`, which does
        # not survive an endpoint's mid-request commit, because commit returns
        # the connection to the pool and the next query gets a fresh one. Every
        # RLS test in the suite ran against the copy, so the defect was invisible
        # to all of them — and a fix to production would not have reached them
        # either.
        #
        # A test double that reimplements the thing it is standing in for can
        # only ever prove the double works.
        from app.core.tenant import tenant_session

        async with tenant_session(org_id, test_session_maker) as session:
            yield session

    # FastAPI's dependency-override matches on the original callable.
    # Each override keeps its own ``Depends`` chain so ``get_tenant_org_id``
    # is still resolved against the live JWT and User dependencies.
    fastapi_app.dependency_overrides[db_module.get_db] = _override_get_db
    fastapi_app.dependency_overrides[get_tenant_db] = _override_get_tenant_db

    yield fastapi_app

    fastapi_app.dependency_overrides.clear()
    for module, original in original_session_locals.items():
        module.AsyncSessionLocal = original
    for module, original in original_engines.items():
        module.engine = original
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


# --- Kafka / Redpanda (shared by the e2e modules) --------------------------
class _RedpandaContainer:
    """Run Redpanda through testcontainers' generic Docker container API."""

    _START_SCRIPT = "/var/lib/redpanda/tc-start.sh"
    _KAFKA_PORT = 9092

    def __init__(self, image: str):
        from testcontainers.core.container import DockerContainer

        self._container = DockerContainer(image, entrypoint="sh")
        self._container.with_exposed_ports(self._KAFKA_PORT)

    def get_bootstrap_server(self) -> str:
        host = self._container.get_container_host_ip()
        port = self._container.get_exposed_port(self._KAFKA_PORT)
        return f"{host}:{port}"

    def start(self):
        from testcontainers.core.waiting_utils import wait_for_logs

        script = self._START_SCRIPT
        self._container.with_command(
            f'-c "while [ ! -f {script} ]; do sleep 0.1; done; sh {script}"'
        )
        self._container.start()

        host = self._container.get_container_host_ip()
        port = self._container.get_exposed_port(self._KAFKA_PORT)
        contents = dedent(
            f"""
            #!/bin/bash
            /usr/bin/rpk redpanda start --mode dev-container --smp 1 --memory 1G \
              --kafka-addr PLAINTEXT://0.0.0.0:29092,OUTSIDE://0.0.0.0:9092 \
              --advertise-kafka-addr \
                PLAINTEXT://127.0.0.1:29092,OUTSIDE://{host}:{port}
            """
        ).strip().encode("utf-8")

        with BytesIO() as archive:
            with tarfile.TarFile(fileobj=archive, mode="w") as tar:
                dirname, basename = os.path.split(script)
                info = tarfile.TarInfo(name=basename)
                info.size = len(contents)
                info.mtime = time.time()
                tar.addfile(info, BytesIO(contents))
            archive.seek(0)
            self._container.get_wrapped_container().put_archive(dirname, archive)

        wait_for_logs(
            self._container,
            r".*Started Kafka API server.*",
            timeout=15,
        )
        self._await_reachable(host, int(port))
        return self

    @staticmethod
    def _await_reachable(host: str, port: int, timeout: float = 45.0) -> None:
        """Block until the broker actually accepts a connection FROM THE HOST.

        The log wait above is necessary and not sufficient. "Started Kafka API
        server" is printed when Redpanda binds inside the container; the host's
        published port can take meaningfully longer to start forwarding, and on a
        Docker-in-VM setup (colima, Docker Desktop) that gap widens with the
        number of running containers.

        The symptom was a `KafkaConnectionError: Unable to bootstrap` that only
        appeared in a FULL test run and never in isolation — the classic shape of
        a readiness check that returns too early. It was read as flakiness; it is
        a race, and it has a right answer: wait for the thing you actually need,
        which is a connection, not a log line.
        """
        deadline = time.time() + timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=2.0):
                    return
            except OSError as exc:  # not listening yet, or not forwarded yet
                last_error = exc
                time.sleep(0.25)
        raise RuntimeError(
            f"Redpanda logged that it started but {host}:{port} never became "
            f"reachable within {timeout}s (last error: {last_error})"
        )

    def stop(self):
        self._container.stop()


@pytest.fixture(scope="session")
def redpanda_container():
    """ONE broker per test session, shared by every Kafka-dependent e2e module.

    This used to be duplicated: an identical _RedpandaContainer lived in both
    test_ingestion_redpanda_e2e and test_compliance_reports_e2e, the latter
    MODULE-scoped and imported by a third module — so a single pytest run started
    several brokers, and they interfered. Those files then appeared "flaky" while
    each passed in isolation. One session-scoped container fixes it at the root
    rather than excluding the tests.

    Still isolated per RUN (fresh container), so consumer offsets cannot leak
    between runs.
    """
    container = _RedpandaContainer(
        image="docker.redpanda.com/redpandadata/redpanda:v23.3.5"
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def redpanda_bootstrap_server(redpanda_container) -> str:
    return redpanda_container.get_bootstrap_server()
