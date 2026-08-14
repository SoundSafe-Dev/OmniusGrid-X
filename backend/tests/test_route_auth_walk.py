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

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Route

from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db
from app.db.database import get_db
from app.main import app
from app.middleware.rbac import require_admin, require_operator_or_admin

# Public by design: no credential of any kind required.
PUBLIC_REQUIRED_EXACT = {
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
    "/api/v1/auth/refresh",    # refresh token in body is the credential
}

PUBLIC_EXACT = PUBLIC_REQUIRED_EXACT

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
    "/api/v1/auth/invitations/",     # one-time invitation token in body
)

# Explicit contract: these mounted routes must retain the canonical admin
# dependency. Any addition or removal requires a deliberate inventory update.
ADMIN_ROUTE_INVENTORY = {
    ("DELETE", "/api/v1/api-keys/{key_id}"),
    ("DELETE", "/api/v1/assets/{asset_id}"),
    ("DELETE", "/api/v1/compliance/reports/schedules/{schedule_id}"),
    ("DELETE", "/api/v1/compliance/security-assets/{asset_id}"),
    ("DELETE", "/api/v1/data-residency/tag/{table_name}/{record_id}"),
    ("DELETE", "/api/v1/data-retention/policies/{metric_name}"),
    ("DELETE", "/api/v1/exports/schedules/{schedule_id}"),
    ("DELETE", "/api/v1/exports/templates/{template_id}"),
    ("DELETE", "/api/v1/feature-flags/{key}"),
    # Admin user management (FS-221). Every route on the router carries
    # require_admin; these entries are the deliberate review of that.
    ("DELETE", "/api/v1/users/{user_id}"),
    ("DELETE", "/api/v1/fleet/cohorts/{cohort_id}"),
    ("DELETE", "/api/v1/fleet/groups/{group_id}"),
    ("DELETE", "/api/v1/fleet/groups/{group_id}/assets/{asset_id}"),
    ("DELETE", "/api/v1/fleet/maintenance-windows/{window_id}"),
    ("DELETE", "/api/v1/fleet/sites/{site_id}"),
    ("DELETE", "/api/v1/fleet/tags/{tag_id}"),
    ("DELETE", "/api/v1/fleet/tags/{tag_id}/assets/{asset_id}"),
    ("DELETE", "/api/v1/gdpr/admin/users/{user_id}/data-delete"),
    ("DELETE", "/api/v1/auth/users/{user_id}"),
    ("DELETE", "/api/v1/auth/users/invitations/{invitation_id}"),
    ("DELETE", "/api/v1/kanban/rules/{rule_id}"),
    ("DELETE", "/api/v1/registries/correlations/{correlation_id}"),
    ("DELETE", "/api/v1/registries/items/{item_id}"),
    ("DELETE", "/api/v1/registries/{registry_id}"),
    ("GET", "/admin/system/status"),
    ("GET", "/api/v1/admin/query-performance/cache-hit-ratio"),
    ("GET", "/api/v1/admin/query-performance/frequent-queries"),
    ("GET", "/api/v1/admin/query-performance/history"),
    ("GET", "/api/v1/admin/query-performance/index-usage"),
    ("GET", "/api/v1/admin/query-performance/missing-indexes"),
    ("GET", "/api/v1/admin/query-performance/query-analysis"),
    ("GET", "/api/v1/admin/query-performance/slow-queries"),
    ("GET", "/api/v1/admin/query-performance/table-bloat"),
    ("GET", "/api/v1/admin/query-performance/table-performance"),
    ("POST", "/api/v1/admin/query-performance/record-snapshot"),
    ("POST", "/api/v1/admin/query-performance/refresh-frequent-queries"),
    ("POST", "/api/v1/admin/query-performance/reset-stats"),
    ("GET", "/api/v1/registries"),
    ("GET", "/api/v1/registries/correlations"),
    ("GET", "/api/v1/registries/{registry_id}"),
    ("GET", "/api/v1/registries/{registry_id}/items"),
    ("PUT", "/api/v1/organizations/settings/current"),
    ("GET", "/api/v1/admin/errors"),
    ("GET", "/api/v1/admin/errors/"),
    ("GET", "/api/v1/admin/errors/summary"),
    ("GET", "/api/v1/admin/errors/{fingerprint}"),
    ("GET", "/api/v1/audit/actions"),
    ("GET", "/api/v1/audit/logs"),
    ("GET", "/api/v1/audit/logs/{log_id}"),
    ("GET", "/api/v1/audit/summary"),
    ("GET", "/api/v1/audit/verify"),
    ("GET", "/api/v1/compliance/reports/schedules"),
    ("GET", "/api/v1/compliance/reports/schedules/{schedule_id}"),
    ("GET", "/api/v1/edge/fleet"),
    ("GET", "/api/v1/edge/fleet/{agent_id}"),
    ("GET", "/api/v1/exports/definitions"),
    ("GET", "/api/v1/exports/deliveries"),
    ("GET", "/api/v1/exports/jobs/{job_id}"),
    ("GET", "/api/v1/exports/jobs/{job_id}/download"),
    ("GET", "/api/v1/exports/kanban/tasks"),
    ("GET", "/api/v1/exports/oee/summary"),
    ("GET", "/api/v1/exports/oee/{asset_id}"),
    ("GET", "/api/v1/exports/registries"),
    ("GET", "/api/v1/exports/registries/{registry_id}/items"),
    ("GET", "/api/v1/exports/schedules"),
    ("GET", "/api/v1/exports/schedules/{schedule_id}"),
    ("GET", "/api/v1/exports/telemetry/{asset_id}"),
    ("GET", "/api/v1/exports/templates"),
    ("GET", "/api/v1/exports/templates/{template_id}"),
    ("GET", "/api/v1/feature-flags/"),
    ("GET", "/api/v1/feature-flags/{key}"),
    ("GET", "/api/v1/users/"),
    ("GET", "/api/v1/users/{user_id}"),
    ("GET", "/api/v1/gdpr/admin/users/{user_id}/data-export"),
    ("GET", "/api/v1/auth/users"),
    ("GET", "/api/v1/auth/users/{user_id}"),
    ("GET", "/api/v1/auth/users/invitations"),
    ("GET", "/api/v1/registries/{registry_id}/score"),
    ("PATCH", "/api/v1/admin/errors/{fingerprint}"),
    ("PATCH", "/api/v1/auth/users/{user_id}"),
    ("PATCH", "/api/v1/fleet/cohorts/{cohort_id}"),
    ("PATCH", "/api/v1/fleet/groups/{group_id}"),
    ("PATCH", "/api/v1/fleet/maintenance-windows/{window_id}"),
    ("PATCH", "/api/v1/fleet/sites/{site_id}"),
    ("PATCH", "/api/v1/fleet/tags/{tag_id}"),
    ("PATCH", "/api/v1/fleet/workcells/{workcell_id}/site"),
    ("POST", "/admin/assets/{asset_id}/maintenance"),
    ("POST", "/admin/database/vacuum"),
    ("POST", "/api/v1/api-keys/generate"),
    ("POST", "/api/v1/auth/users/{user_id}/reactivate"),
    ("POST", "/api/v1/auth/users/invitations"),
    ("POST", "/api/v1/auth/users/invitations/{invitation_id}/resend"),
    ("POST", "/api/v1/assets/"),
    ("POST", "/api/v1/bulk/assets/import"),
    ("POST", "/api/v1/bulk/jobs/{job_id}/cancel"),
    ("POST", "/api/v1/bulk/registries/{registry_id}/items"),
    ("POST", "/api/v1/commands/asset/{asset_id}/emergency-stop"),
    ("POST", "/api/v1/compliance/reports"),
    ("POST", "/api/v1/compliance/reports/schedules"),
    ("POST", "/api/v1/compliance/security-assets"),
    ("POST", "/api/v1/compliance/vendor-assessments"),
    ("POST", "/api/v1/data-residency/tag"),
    ("POST", "/api/v1/data-residency/validate"),
    ("POST", "/api/v1/data-retention/enforce"),
    ("POST", "/api/v1/data-retention/policies"),
    ("POST", "/api/v1/engines/cloud/flush"),
    ("POST", "/api/v1/engines/correlation/integration/initialize-registries"),
    ("POST", "/api/v1/engines/correlation/integration/test-integration"),
    ("POST", "/api/v1/engines/mlops/deploy/{version}"),
    ("POST", "/api/v1/engines/mlops/rollback"),
    ("POST", "/api/v1/exports/schedules"),
    ("POST", "/api/v1/exports/templates"),
    ("POST", "/api/v1/feature-flags/"),
    ("PATCH", "/api/v1/users/{user_id}"),
    ("POST", "/api/v1/users/"),
    ("POST", "/api/v1/fleet/model-releases"),
    ("POST", "/api/v1/fleet/cohorts"),
    ("POST", "/api/v1/fleet/groups"),
    ("POST", "/api/v1/fleet/maintenance-windows"),
    ("POST", "/api/v1/fleet/maintenance-windows/preview"),
    ("POST", "/api/v1/fleet/releases"),
    ("POST", "/api/v1/fleet/releases/agent"),
    ("POST", "/api/v1/fleet/releases/{release_id}/publish"),
    ("POST", "/api/v1/fleet/releases/{release_id}/yank"),
    ("POST", "/api/v1/fleet/rollouts"),
    ("POST", "/api/v1/fleet/rollouts/{rollout_id}/cancel"),
    ("POST", "/api/v1/fleet/rollouts/{rollout_id}/pause"),
    ("POST", "/api/v1/fleet/rollouts/{rollout_id}/resume"),
    ("POST", "/api/v1/fleet/sites"),
    ("POST", "/api/v1/fleet/tags"),
    ("POST", "/api/v1/fleet/tags/bulk-assignments"),
    ("POST", "/api/v1/fleet/target-previews"),
    ("POST", "/api/v1/gdpr/processing-records"),
    ("POST", "/api/v1/kanban/rules"),
    ("POST", "/api/v1/kanban/rules/{rule_id}/test"),
    ("POST", "/api/v1/models/{model_id}/publish"),
    ("POST", "/api/v1/models/{model_id}/yank"),
    ("POST", "/api/v1/models/{name}/train"),
    ("POST", "/api/v1/registries"),
    ("POST", "/api/v1/registries/correlations"),
    ("POST", "/api/v1/registries/items/{item_id}/score"),
    ("POST", "/api/v1/registries/{registry_id}/items"),
    ("PUT", "/api/v1/assets/{asset_id}"),
    ("PUT", "/api/v1/compliance/reports/schedules/{schedule_id}"),
    ("PUT", "/api/v1/compliance/security-assets/{asset_id}"),
    ("PUT", "/api/v1/compliance/vendor-assessments/{assessment_id}"),
    ("PUT", "/api/v1/data-retention/policies/{metric_name}"),
    ("PUT", "/api/v1/exports/schedules/{schedule_id}"),
    ("PUT", "/api/v1/exports/templates/{template_id}"),
    ("PUT", "/api/v1/feature-flags/{key}"),
    ("PUT", "/api/v1/fleet/groups/{group_id}/assets/{asset_id}"),
    ("PUT", "/api/v1/fleet/tags/{tag_id}/assets/{asset_id}"),
    ("PUT", "/api/v1/kanban/rules/{rule_id}"),
    ("PUT", "/api/v1/registries/correlations/{correlation_id}"),
    ("PUT", "/api/v1/registries/items/{item_id}"),
    ("PUT", "/api/v1/registries/{registry_id}"),
}

SELF_SERVICE_MUTATIONS = {
    ("DELETE", "/api/v1/gdpr/data-delete"),
    ("DELETE", "/api/v1/nlp/sessions/{session_id}"),
    ("DELETE", "/api/v1/nlp/sessions/{session_id}/data/{source_id}"),
    ("DELETE", "/api/v1/user/goals/{goal_id}"),
    ("POST", "/api/v1/gdpr/consent"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/kanban/board/view"),
    ("POST", "/api/v1/nlp/correlation/chat"),
    ("POST", "/api/v1/nlp/correlation/intake/analyze"),
    ("POST", "/api/v1/nlp/correlation/intake/upload"),
    ("POST", "/api/v1/nlp/correlation/query"),
    ("POST", "/api/v1/nlp/sessions"),
    ("POST", "/api/v1/nlp/sessions/cleanup-orphaned"),
    ("POST", "/api/v1/nlp/sessions/{session_id}/chat"),
    ("POST", "/api/v1/nlp/sessions/{session_id}/data/intake"),
    ("POST", "/api/v1/nlp/sessions/{session_id}/data/upload"),
    ("POST", "/api/v1/nlp/sessions/{session_id}/generate-title"),
    ("POST", "/api/v1/nlp/sessions/{session_id}/resume"),
    ("POST", "/api/v1/user/goals"),
    ("PUT", "/api/v1/gdpr/consent/{consent_id}/withdraw"),
    ("PUT", "/api/v1/nlp/sessions/{session_id}"),
    ("PUT", "/api/v1/user/context"),
    ("PUT", "/api/v1/user/goals/{goal_id}"),
}

CREDENTIAL_MUTATIONS = {
    ("POST", "/api/v1/auth/invitations/accept"),
    ("POST", "/api/v1/auth/invitations/validate"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/geotab/webhook"),
    ("POST", "/api/v1/sso/login/callback"),
}

# Pre-existing authenticated operational mutations that predate the integration
# branch's RBAC sweep (its inventory was built on a 150-commit-stale base). Every
# route here already enforces authentication (test_every_route_rejects_
# unauthenticated_requests covers that) via get_current_active_user, an agent
# certificate (edge/*), or an HMAC/webhook secret (erp/webhooks). Fine-grained
# role tightening is tracked as an FS-73 follow-up; listing them keeps this test
# a live guard for any NEW unclassified mutation without changing runtime auth.
AUTHENTICATED_OPERATIONAL_MUTATIONS = {
    # The correlation-evidence and operations-assistant routers, arriving with the
    # correlation-engine merge. Each was checked for `get_current_active_user` before being
    # listed here rather than assumed from the router: this set's whole value is that
    # membership is a statement somebody verified. They are tenant-scoped through
    # `get_tenant_db`, which the same merge needed fixing to obtain — the four handlers that
    # read `intake_items` had `get_db`, and that table is FORCE ROW LEVEL SECURITY, so an
    # untenanted session reads zero rows and raises nothing.
    #
    # Role tightening is Harsh's to decide, as with /api/v1/nlp beside it. Two are worth his
    # attention: `evidence/vocabulary/{feedback_id}/review` is a REVIEW action any
    # authenticated member can currently take, and `actions/decide` records an approval
    # decision — both read as approver-role surfaces rather than member ones.
    ("POST", "/api/v1/correlation/evidence/connectors/{connector}/plan"),
    ("POST", "/api/v1/correlation/evidence/intake/catalog"),
    ("POST", "/api/v1/correlation/evidence/intake/preview"),
    ("POST", "/api/v1/correlation/evidence/intake/analytics"),
    ("POST", "/api/v1/correlation/evidence/intake/jobs"),
    ("DELETE", "/api/v1/correlation/evidence/jobs/{job_id}"),
    ("POST", "/api/v1/correlation/evidence/evaluations/run"),
    ("POST", "/api/v1/correlation/evidence/evaluations/evidence"),
    ("POST", "/api/v1/correlation/evidence/vocabulary"),
    ("POST", "/api/v1/correlation/evidence/vocabulary/{feedback_id}/review"),
    ("POST", "/api/v1/correlation/evidence/actions/assess"),
    ("POST", "/api/v1/correlation/evidence/actions/decide"),
    ("POST", "/api/v1/correlation/operations/answer"),
    ("POST", "/api/v1/correlation/operations/briefing"),
    ("POST", "/api/v1/correlation/operations/jobs/{job_id}/answer"),
    ("POST", "/api/v1/transportation/vehicles"),
    ("POST", "/api/v1/simulation/monte-carlo"),
    ("POST", "/api/v1/notifications/subscriptions"),
    ("DELETE", "/api/v1/notifications/subscriptions/{subscription_id}"),
    # P11. Same classification as its POST and DELETE siblings above: authenticated and
    # tenant-scoped, with the org filter and RLS both proven in
    # test_notification_tenant_isolation_realdb.py. A cross-tenant UPDATE is the sharper
    # of the two — it can retarget another org's alerts rather than merely destroy them —
    # which is why that file drives the retarget attempt explicitly.
    ("PATCH", "/api/v1/notifications/subscriptions/{subscription_id}"),
    ("POST", "/api/v1/notifications/test"),
    ("POST", "/api/v1/edge/enroll"),
    ("POST", "/api/v1/edge/ingest"),
    ("POST", "/api/v1/edge/heartbeat"),
    ("POST", "/api/v1/nlp/correlation/intake/cross-correlate"),
    ("POST", "/api/v1/nlp/sessions/{session_id}/correlate"),
    ("POST", "/api/v1/erp/integrations"),
    ("PUT", "/api/v1/erp/integrations/{integration_id}"),
    ("DELETE", "/api/v1/erp/integrations/{integration_id}"),
    ("POST", "/api/v1/erp/integrations/{integration_id}/test"),
    ("POST", "/api/v1/erp/integrations/{integration_id}/sync"),
    ("POST", "/api/v1/erp/integrations/{integration_id}/mappings"),
    ("PUT", "/api/v1/erp/integrations/{integration_id}/mappings/{mapping_id}"),
    ("DELETE", "/api/v1/erp/integrations/{integration_id}/mappings/{mapping_id}"),
    ("POST", "/api/v1/erp/webhooks/{erp_type}"),
    ("POST", "/api/v1/nlp/sessions/{session_id}/platform-data"),
    ("POST", "/api/v1/geofencing/zones"),
    ("PUT", "/api/v1/geofencing/zones/{zone_id}"),
    ("DELETE", "/api/v1/geofencing/zones/{zone_id}"),
    ("POST", "/api/v1/geofencing/alerts/{alert_id}/acknowledge"),
    ("PATCH", "/api/v1/maintenance/schedules/{schedule_id}"),
    ("POST", "/api/v1/maintenance/schedules"),
    ("PATCH", "/api/v1/maintenance/repair-orders/{order_id}"),
    ("POST", "/api/v1/maintenance/history"),
    ("POST", "/api/v1/maintenance/repair-orders"),
    # RAG compliance-doc pipeline (Hudson): authenticated ingest/query/delete.
    ("POST", "/api/v1/rag/ingest"),
    ("POST", "/api/v1/rag/query"),
    ("DELETE", "/api/v1/rag/documents/{doc_id}"),
    # Presigns a document the caller was already shown as a citation, so it is a
    # POST only to keep the S3 key out of URLs and access logs — it mutates
    # nothing. Any authenticated member of the org may open their own org's
    # documents; the handler rejects a key outside the caller's `{org_id}/`
    # prefix before it reaches the store.
    ("POST", "/api/v1/rag/documents/link"),
    # model-monitoring (Harsh, MLOps drift) is authenticated. The admin
    # query-performance mutations + org-settings PUT moved to the
    # ADMIN_ROUTE_INVENTORY when their gate was consolidated onto the canonical
    # rbac.require_admin (graph-walk discovers them now).
    ("POST", "/api/v1/model-monitoring/drift/detect"),
    ("POST", "/api/v1/model-monitoring/data-drift/detect"),
    ("POST", "/api/v1/model-monitoring/performance/prediction"),
    ("POST", "/api/v1/model-monitoring/reset/{model_id}"),
}


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


# The traversal moved to tests/_route_tree.py when a second guard
# (test_response_model_coverage_ratchet) needed it. Copying it would have given
# the two walks freedom to regress independently — defect class 7, a test double
# that reimplements what it stands in for — and the failure mode here is silent:
# a walk that stops recursing sees 2 routes of 453 and passes.
from tests._route_tree import flatten as _flatten  # noqa: E402


def _http_routes():
    seen = set()
    for route, prefix in _flatten(app.routes):
        if not isinstance(route, Route):  # skips WebSocketRoute (/ws) + mounts
            continue
        path = prefix + route.path
        if path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
            continue
        methods = (getattr(route, "methods", None) or set()) - {"HEAD", "OPTIONS"}
        for method in sorted(methods):
            if (method, path) in seen:
                continue
            seen.add((method, path))
            yield method, path


def _dependency_tree_contains(dependant, dependency) -> bool:
    if getattr(dependant, "call", None) is dependency:
        return True
    return any(
        _dependency_tree_contains(child, dependency)
        for child in getattr(dependant, "dependencies", ())
    )


def _admin_routes():
    seen = set()
    for route, prefix in _flatten(app.routes):
        if not isinstance(route, APIRoute):
            continue
        if not _dependency_tree_contains(route.dependant, require_admin):
            continue
        path = prefix + route.path
        methods = (route.methods or set()) - {"HEAD", "OPTIONS"}
        for method in methods:
            if (method, path) not in seen:
                seen.add((method, path))
                yield method, path


def _operator_routes():
    seen = set()
    for route, prefix in _flatten(app.routes):
        if not isinstance(route, APIRoute):
            continue
        if not _dependency_tree_contains(
            route.dependant, require_operator_or_admin
        ):
            continue
        path = prefix + route.path
        methods = (route.methods or set()) - {"HEAD", "OPTIONS"}
        for method in methods:
            if (method, path) not in seen:
                seen.add((method, path))
                yield method, path


def _mutation_routes():
    seen = set()
    for route, prefix in _flatten(app.routes):
        if not isinstance(route, APIRoute):
            continue
        path = prefix + route.path
        methods = (route.methods or set()) & {"POST", "PUT", "PATCH", "DELETE"}
        for method in methods:
            if (method, path) in seen:
                continue
            seen.add((method, path))
            yield method, path, route.dependant


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


def test_admin_route_inventory_matches_dependency_graph():
    discovered = set(_admin_routes())

    assert ADMIN_ROUTE_INVENTORY, "admin route inventory must not be empty"
    assert discovered, "no routes use the canonical require_admin dependency"
    assert discovered == ADMIN_ROUTE_INVENTORY, (
        "Admin dependency inventory is stale. Missing gates: "
        f"{sorted(ADMIN_ROUTE_INVENTORY - discovered)}; "
        f"unreviewed admin routes: {sorted(discovered - ADMIN_ROUTE_INVENTORY)}"
    )


# Endpoints the frontend's admin-only pages (/admin/*) call. The inventory above
# is a *regression lock* — it records what is currently admin-gated and notices
# drift — but it never asserts what *should* be gated, and it is shaped around
# the /api/v1/admin/ path prefix. So an admin-UI endpoint living outside that
# prefix was invisible to it: GET /api/v1/edge/fleet backs /admin/collectors and
# required only an authenticated user, letting any tenant enumerate every
# organization's edge agents. This list is the policy side of the contract; add
# an entry whenever an admin page starts calling a new endpoint.
ADMIN_UI_BACKED_ROUTES = {
    ("GET", "/api/v1/edge/fleet"): "frontend /admin/collectors",
    ("GET", "/api/v1/edge/fleet/{agent_id}"): "frontend /admin/collectors",
    ("GET", "/api/v1/admin/errors"): "frontend /admin/errors",
    ("GET", "/api/v1/admin/errors/{fingerprint}"): "frontend /admin/errors/:fingerprint",
}


def test_admin_ui_backed_routes_require_admin():
    """Every endpoint behind an /admin/* page must carry the admin dependency."""
    discovered = set(_admin_routes())

    ungated = [
        f"{method} {path}  (backs {page})"
        for (method, path), page in sorted(ADMIN_UI_BACKED_ROUTES.items())
        if (method, path) not in discovered
    ]
    assert not ungated, (
        "Endpoints behind admin-only UI pages are not admin-gated:\n  "
        + "\n  ".join(ungated)
    )


def test_operator_is_forbidden_on_every_admin_route(client):
    async def _operator():
        return SimpleNamespace(
            id=uuid4(),
            organization_id=uuid4(),
            role="operator",
            is_active=True,
        )

    app.dependency_overrides[get_current_active_user] = _operator
    failures = []
    try:
        for method, path in sorted(ADMIN_ROUTE_INVENTORY):
            response = client.request(method, _probe_path(path))
            if response.status_code != 403:
                failures.append(
                    f"{method} {path} -> {response.status_code}: {response.text[:160]}"
                )
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)

    assert not failures, (
        "Operator reached an admin route or validation ran before RBAC:\n  "
        + "\n  ".join(failures)
    )


def test_every_mutation_has_a_reviewed_role_policy():
    mounted = {
        (method, path)
        for method, path, _dependant in _mutation_routes()
    }
    stale = (
        SELF_SERVICE_MUTATIONS
        | CREDENTIAL_MUTATIONS
        | AUTHENTICATED_OPERATIONAL_MUTATIONS
    ) - mounted
    assert not stale, f"reviewed mutation inventory contains stale routes: {stale}"

    unreviewed = []
    for method, path, dependant in _mutation_routes():
        route = (method, path)
        if (
            route in SELF_SERVICE_MUTATIONS
            or route in CREDENTIAL_MUTATIONS
            or route in AUTHENTICATED_OPERATIONAL_MUTATIONS
        ):
            continue
        if _dependency_tree_contains(
            dependant, require_admin
        ) or _dependency_tree_contains(dependant, require_operator_or_admin):
            continue
        unreviewed.append(route)

    assert not unreviewed, f"mutations without a reviewed role policy: {unreviewed}"


def test_viewer_is_forbidden_on_operational_mutations(client):
    async def _viewer():
        return SimpleNamespace(
            id=uuid4(),
            organization_id=uuid4(),
            role="viewer",
            is_active=True,
        )

    routes = sorted(_operator_routes())
    assert routes, "no routes use the operator/admin dependency"
    app.dependency_overrides[get_current_active_user] = _viewer
    failures = []
    try:
        for method, path in routes:
            response = client.request(method, _probe_path(path))
            if response.status_code != 403:
                failures.append(
                    f"{method} {path} -> {response.status_code}: {response.text[:160]}"
                )
    finally:
        app.dependency_overrides.pop(get_current_active_user, None)

    assert not failures, (
        "Viewer reached an operational mutation or validation ran before RBAC:\n  "
        + "\n  ".join(failures)
    )


def test_allowlist_paths_exist():
    # A stale allowlist hides regressions: every exact entry must still be a
    # real route.
    actual = {prefix + r.path for r, prefix in _flatten(app.routes) if isinstance(r, Route)}
    missing = PUBLIC_REQUIRED_EXACT - actual
    assert not missing, f"allowlisted paths no longer exist: {missing}"
