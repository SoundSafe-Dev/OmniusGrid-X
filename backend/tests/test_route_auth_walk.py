"""Route-walking auth enforcement test (FS-52).

Walks every HTTP route on the real app and asserts that a token-less request
cannot reach a 2xx. This makes the auth gating self-enforcing: the NEXT new
router someone forgets to protect fails this test by name instead of shipping
open.

DB-free by design (works without testcontainers): oauth2_scheme is
auto_error=False and get_current_active_user raises 401 before any query, so
an unauthenticated request never touches the database. get_db is overridden
with a dummy anyway, so any route whose OTHER dependencies would query fails
loudly here rather than hitting a real connection.

Routes that legitimately answer without a user JWT are allowlisted below with
the reason. Signature/bootstrap/agent-authenticated routes are NOT allowlisted
— they must still reject an unauthenticated request (401/403), which this test
accepts as "protected".
"""

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from app.core.tenant import get_tenant_db
from app.db.database import get_db
from app.main import app

# Public by design: no credential of any kind required.
PUBLIC_EXACT = {
    "/",                       # root banner
    "/health",
    "/health/live",
    "/health/ready",
    "/health/startup",
    "/health/redis",           # infra probes, same class as the other health routes
    "/health/db",
    "/health/kafka",
    "/api/v1/health/redis",    # (health router is mounted at both prefixes)
    "/api/v1/health/db",
    "/api/v1/health/kafka",
    "/metrics",                # prometheus scrape
    "/api/v1/sso/status",      # login page discovers SSO availability pre-auth
    "/api/v1/sso/login/callback",  # IdP redirect target; validates its own payload
    "/api/v1/auth/login",
    "/api/v1/auth/register",   # dev-only; gated by ALLOW_OPEN_REGISTRATION
    "/api/v1/auth/refresh",    # authenticates via the refresh token itself
}

# Public-but-otherwise-authenticated: signed URLs, HMAC webhooks, bootstrap
# tokens. A token-less request must still be REJECTED (non-2xx) — these
# prefixes are only exempt from the "must be 401/403/405" strictness because
# they return 400/422 (missing signature/body) instead of 401.
CREDENTIALLESS_PREFIXES = (
    "/api/v1/erp/webhooks",          # HMAC signature
    "/api/v1/geotab/webhook",        # shared-secret header
    "/api/v1/edge/enroll",           # bootstrap token in body
    "/api/v1/exports/",              # public_router signed-URL download
    "/api/v1/fleet/releases/",       # public_router signed bundle download
    "/api/v1/models/",               # public_router signed model download
    "/api/v1/compliance/reports/",   # public_router signed download
)


async def _no_db():
    # Yields an inert non-session: get_db is a SUB-DEPENDENCY of the auth
    # dependency, so it resolves before auth runs — raising here would 500
    # every route. Auth must 401 without ever touching this None; any code
    # path that queries pre-auth explodes into a 500 and lands in the
    # weakly_rejected bucket below.
    yield None


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_db] = _no_db
    app.dependency_overrides[get_tenant_db] = _no_db
    # No context manager: skips lifespan (init_db would try to reach the
    # placeholder DATABASE_URL conftest sets; the walk needs no DB/schedulers).
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_tenant_db, None)


def _http_routes():
    for route in app.routes:
        if not isinstance(route, Route):  # skips WebSocketRoute (/ws) + mounts
            continue
        if route.path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
            continue
        methods = (route.methods or set()) - {"HEAD", "OPTIONS"}
        for method in sorted(methods):
            yield method, route.path


def _probe_path(path: str) -> str:
    # Fill path params with a syntactically valid UUID so routing (not 422
    # path validation) decides the outcome.
    out = []
    for part in path.split("/"):
        if part.startswith("{") and part.endswith("}"):
            out.append("00000000-0000-0000-0000-000000000000")
        else:
            out.append(part)
    return "/".join(out)


def test_every_route_rejects_unauthenticated_requests(client):
    open_routes = []
    weakly_rejected = []

    for method, path in _http_routes():
        if path in PUBLIC_EXACT:
            continue
        resp = client.request(method, _probe_path(path))

        if path.startswith(CREDENTIALLESS_PREFIXES):
            # Signature/bootstrap/signed-URL routes: any rejection is fine,
            # a 2xx without credentials is not.
            if 200 <= resp.status_code < 300:
                open_routes.append(f"{method} {path} -> {resp.status_code}")
            continue

        # User-JWT (or agent-cert) routes must reject outright.
        if 200 <= resp.status_code < 300:
            open_routes.append(f"{method} {path} -> {resp.status_code}")
        elif resp.status_code not in (401, 403, 405):
            # 404/422/400 on a protected route means some dependency ran
            # before auth — not open, but worth surfacing.
            weakly_rejected.append(f"{method} {path} -> {resp.status_code}")

    assert not open_routes, (
        "UNAUTHENTICATED 2xx — these routes are open; add auth or allowlist "
        "with justification:\n  " + "\n  ".join(open_routes)
    )
    assert not weakly_rejected, (
        "Protected routes rejected with a non-auth status (a dependency ran "
        "before auth):\n  " + "\n  ".join(weakly_rejected)
    )


def test_allowlist_paths_exist():
    # A stale allowlist hides regressions: every exact entry must still be a
    # real route.
    actual = {r.path for r in app.routes if isinstance(r, Route)}
    missing = PUBLIC_EXACT - actual
    assert not missing, f"allowlisted paths no longer exist: {missing}"
