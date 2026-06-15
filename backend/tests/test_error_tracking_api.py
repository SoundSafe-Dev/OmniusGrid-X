"""Integration + E2E tests for the Error Triage API (Docker-backed).

Exercises RBAC (401/403/200), the list/summary/detail/status endpoints, and the
full record -> flush -> triage -> regression loop against the ephemeral
container. Reuses the tenant-isolation conftest fixtures.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg2
import pytest
from httpx import ASGITransport, AsyncClient

from app.services.error_tracker import ErrorTracker


BASE = "/api/v1/admin/errors"


# --- helpers -----------------------------------------------------------------

def _exc(msg: str = "boom") -> Exception:
    try:
        raise ValueError(msg)
    except ValueError as e:  # noqa: BLE001
        return e


@pytest.fixture
def clean_error_tables(admin_sync_url):
    """Truncate the error tables before each test for deterministic assertions."""
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE error_event_buckets, error_events CASCADE;")
    finally:
        conn.close()
    yield


async def _record_and_flush(route: str, msg: str = "boom") -> None:
    """Drive the production record+flush path against the rebound test DB."""
    tracker = ErrorTracker()
    await tracker.record(_exc(msg), method="GET", route=route)
    await tracker._flush_once()


def _client_for_role(app, admin_sync_url, seeded_orgs, role: str) -> AsyncClient:
    from app.core.config import settings
    from tests.conftest import _make_jwt

    user_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users
                (id, email, hashed_password, organization_id, role, is_active)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (
                    str(user_id),
                    f"{role}-{user_id.hex[:8]}@test.local",
                    "$2b$12$" + "x" * 53,
                    str(seeded_orgs["org_a_id"]),
                    role,
                    True,
                ),
            )
    finally:
        conn.close()

    token = _make_jwt(user_id, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM)
    transport = ASGITransport(app=app)
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


# --- RBAC --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthenticated_is_rejected(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in (BASE, f"{BASE}/summary", f"{BASE}/deadbeef"):
            resp = await client.get(path)
            assert resp.status_code == 401, path
        resp = await client.patch(f"{BASE}/deadbeef", json={"status": "resolved"})
        assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "viewer"])
async def test_non_admin_forbidden(app, admin_sync_url, seeded_orgs, role):
    async with _client_for_role(app, admin_sync_url, seeded_orgs, role) as client:
        assert (await client.get(BASE)).status_code == 403
        assert (await client.get(f"{BASE}/summary")).status_code == 403
        assert (await client.get(f"{BASE}/deadbeef")).status_code == 403
        resp = await client.patch(f"{BASE}/deadbeef", json={"status": "resolved"})
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_allowed(app, client_a, clean_error_tables):
    assert (await client_a.get(BASE)).status_code == 200
    assert (await client_a.get(f"{BASE}/summary")).status_code == 200


# --- list / summary / detail -------------------------------------------------

@pytest.mark.asyncio
async def test_list_and_summary_reflect_recorded_errors(app, client_a, clean_error_tables):
    await _record_and_flush("/api/v1/alpha")
    await _record_and_flush("/api/v1/alpha")  # same fingerprint -> count 2
    await _record_and_flush("/api/v1/beta")

    listing = (await client_a.get(BASE, params={"range": "all"})).json()
    assert listing["total"] == 2
    by_route = {item["route"]: item for item in listing["items"]}
    assert by_route["/api/v1/alpha"]["total_count"] == 2
    assert by_route["/api/v1/beta"]["total_count"] == 1
    # Default sort is by count desc -> alpha first.
    assert listing["items"][0]["route"] == "/api/v1/alpha"

    summary = (await client_a.get(f"{BASE}/summary", params={"range": "all"})).json()
    assert summary["open_count"] == 2
    assert summary["events_in_range"] == 3
    assert summary["top_error"]["route"] == "/api/v1/alpha"


@pytest.mark.asyncio
async def test_search_and_pagination(app, client_a, clean_error_tables):
    await _record_and_flush("/api/v1/alpha")
    await _record_and_flush("/api/v1/beta")

    filtered = (await client_a.get(BASE, params={"q": "alpha", "range": "all"})).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["route"] == "/api/v1/alpha"

    page = (await client_a.get(BASE, params={"limit": 1, "range": "all"})).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1

    too_big = await client_a.get(BASE, params={"limit": 1000})
    assert too_big.status_code == 422  # limit cap enforced


@pytest.mark.asyncio
async def test_detail_404_for_unknown(app, client_a, clean_error_tables):
    resp = await client_a.get(f"{BASE}/notarealfingerprint")
    assert resp.status_code == 404


# --- status workflow + regression -------------------------------------------

@pytest.mark.asyncio
async def test_status_transitions(app, client_a, clean_error_tables):
    await _record_and_flush("/api/v1/gamma")
    fp = (await client_a.get(BASE, params={"range": "all"})).json()["items"][0]["fingerprint"]

    ack = await client_a.patch(f"{BASE}/{fp}", json={"status": "acknowledged"})
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["status_changed_by"] is not None

    resolved = await client_a.patch(f"{BASE}/{fp}", json={"status": "resolved"})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    # resolved -> acknowledged is not a permitted transition.
    bad = await client_a.patch(f"{BASE}/{fp}", json={"status": "acknowledged"})
    assert bad.status_code == 422

    missing = await client_a.patch(f"{BASE}/deadbeef", json={"status": "open"})
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_resolved_error_auto_reopens_on_regression(app, client_a, clean_error_tables):
    await _record_and_flush("/api/v1/delta", msg="contact admin@corp.com please")
    fp = (await client_a.get(BASE, params={"range": "all"})).json()["items"][0]["fingerprint"]

    # Traceback/message must be scrubbed end-to-end.
    detail = (await client_a.get(f"{BASE}/{fp}")).json()
    assert "admin@corp.com" not in (detail["message_sample"] or "")
    assert "admin@corp.com" not in (detail["traceback_sample"] or "")
    assert "<email>" in (detail["message_sample"] or "")

    # Resolve it...
    await client_a.patch(f"{BASE}/{fp}", json={"status": "resolved"})

    # ...then the same error recurs.
    await _record_and_flush("/api/v1/delta", msg="contact admin@corp.com please")

    after = (await client_a.get(f"{BASE}/{fp}")).json()
    assert after["status"] == "open"           # auto-reopened
    assert after["regression_count"] == 1
    assert after["total_count"] == 2
