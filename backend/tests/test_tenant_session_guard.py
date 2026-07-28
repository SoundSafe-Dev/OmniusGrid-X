"""Guard: routers must not query RLS-protected tables through ``get_db`` (FS-201).

``get_db`` yields a plain session and never sets the ``app.current_org_id`` GUC.
Most tenant tables are ``FORCE ROW LEVEL SECURITY`` with a policy of

    USING (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)

so with no GUC the predicate is NULL and **every row is filtered**. It does not
raise — the endpoint just returns nothing. That is exactly how the dashboard
shipped rendering zeros (FS-191) and how the audit trail was silently empty
before it: a whole class of bugs that fails quiet.

This test is static analysis, deliberately: it catches the shape before anyone
has to notice missing data in a UI. It asserts in BOTH directions, like
``KNOWN_LANE_FAILURES`` in test_realdb_endpoint_smoke:

  * a router that starts using ``get_db`` on an RLS table and isn't listed FAILS
    (no new debt);
  * a router listed here that no longer has the problem also FAILS (the list
    can't rot into a lie).

To fix a router: swap ``Depends(get_db)`` for ``Depends(get_tenant_db)`` (and
take the org from ``get_tenant_org_id``, never from client input), then delete
its entry below.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
API_DIR = BACKEND / "app" / "api"
MODELS = BACKEND / "app" / "db" / "models.py"
MIGRATIONS = BACKEND.parent / "database" / "migrations"

# Routers with NO authenticated user by design — `get_tenant_db` depends on
# `get_current_active_user`, so converting these would break them outright.
# These are exempt, not debt.
NO_USER_CONTEXT = {
    # Agent client-certificate auth (require_agent); the identity is the cert,
    # not a user. Tenancy comes from the verified agent record instead.
    "edge_ingest.py",
    # Unauthenticated vendor callback. The tenant is whoever holds the secret that
    # verifies the raw bytes, so the candidate lookup must span organizations by
    # construction and no user context exists to derive one from. Exempt from THIS
    # guard, but currently broken for a related reason — see the note below.
    "erp_webhooks.py",
}
# NOTE: health.py was initially exempted as "infra probes", but it is a MIXED
# file — /health/ready and /health/startup are unauthenticated probes while
# /health/detailed is admin-gated and counts Assets/Alarms. A blanket exemption
# would have hidden that second half, so it is listed as debt below instead.

# Known debt: routers still reading RLS-protected tables through `get_db`.
# The number is how many `Depends(get_db)` sites that router has — pinned so a
# partial fix still moves, and so nothing silently grows.
KNOWN_GET_DB_ON_RLS: dict[str, int] = {
    # analysis_sessions.py is GONE from this list, and it is the one entry that did
    # NOT fail quietly. `analysis_sessions` is RLS-protected and all 22 handlers ran on
    # get_db, so reads matched nothing (empty list, 404 by id) while CREATE raised
    # InsufficientPrivilegeError — a 500 — because the policy's WITH CHECK rejects an
    # INSERT made with no tenant GUC. Under RLS a read fails silently and a write fails
    # loudly; every other entry on this list was the quiet kind, which is why they
    # lasted. The application layer was already correct
    # (organization_id=current_user.organization_id on create); only the GUC was
    # missing. Pinned by tests/test_analysis_sessions_tenant_scoping_realdb.py.
    # 4, not 5, and the split has now been done. /admin/system/status is admin-gated
    # with a real user and was on get_db, so its assets and alarms counts — both FORCE
    # RLS — came back ZERO regardless of what existed. A system-status page reporting
    # no active assets on a running platform reads as an idle system, not a broken
    # query. It is now tenant-scoped.
    #
    # The remaining 4 sites are the UNAUTHENTICATED probes (/health/live, /ready,
    # /startup and their shared checks). They cannot use get_tenant_db, which resolves
    # a tenant from a user they do not have, so they read only tables without a policy
    # — which is why _check_ingestion had to drop its assets.last_seen read. They are
    # exempt in substance but stay counted here so the number cannot drift unnoticed.
    # Pinned by tests/test_admin_system_status_scoping_realdb.py.
    "health.py": 4,
    # audit.py and gdpr.py are GONE from this list. Both were the empty-page failure:
    # audit_logs and data_processing_records have had tenant policies since migration
    # 011, and every handler ran on get_db, so the policy matched nothing and the
    # endpoints returned ZERO rows — including for the caller's own organization. The
    # audit trail was silently blank, which is the one thing an audit trail must not be.
    #
    # gdpr.py is the sharper case: its handlers filtered on current_user.organization_id
    # CORRECTLY and it made no difference, because RLS had already removed the row.
    # Pinned by tests/test_audit_and_gdpr_tenant_scoping_realdb.py.
    # commands.py is GONE from this list, and the count it carried was WRONG in an
    # instructive way. This guard looks for `Depends(get_db)` and found one site; two
    # more handlers — submit_command and emergency_stop — opened
    # `AsyncSessionLocal()` inline, which the guard cannot see. `assets` is FORCE RLS,
    # so all three looked up the asset through a session with no GUC, got None, and
    # answered 404 for EVERY asset including the caller's own. Command submission was
    # impossible, history was empty, and the admin-gated emergency stop was
    # unreachable. Verified against a real database; pinned by
    # tests/test_command_dispatch_tenant_scoping_realdb.py.
    #
    # A static guard keyed on one idiom under-counts a file that uses two.
    #
    # erp_webhooks.py is EXEMPT rather than fixed, and is not debt of this kind. The
    # receiver is an unauthenticated vendor callback: there is no user, so
    # get_tenant_db (which depends on get_current_active_user) cannot apply, and the
    # tenant is resolved by which stored secret verifies the raw bytes — a lookup that
    # must span organizations by construction. It is nonetheless BROKEN: verified
    # against a real database, every inbound webhook is rejected 404 because
    # integration_configurations has FORCE RLS and the candidate lookup returns
    # nothing. Fixing it needs a design decision (a privileged read path, or the
    # tenant in the URL), not a dependency swap. Recorded in
    # docs/engineering/defect-class-sweeps.md.
    # fleet_logistics.py is GONE from this list. All 23 handlers moved to
    # get_tenant_db, and the four tables that have no RLS to fall back on
    # (geofence_zones, geofence_alerts, maintenance_schedules, repair_orders) are
    # now filtered explicitly via `_scope`. It was not merely on the wrong
    # dependency: the zone list returned every tenant's zones, and fetch-by-id was
    # a full IDOR — both confirmed against a real database. Its four create paths
    # also took organization_id from the client payload and now take it from the
    # token. Pinned by tests/test_fleet_logistics_tenant_isolation_realdb.py.
    "kanban.py": 10,
    # logistics_correlation.py and platform_correlation.py are GONE from this list.
    # Both queried RLS-protected tables (dock_appointments, analysis_sessions) through
    # get_db, so every endpoint returned an empty result — logistics_correlation even
    # filtered on organization_id correctly itself, which made no difference because
    # RLS had already removed the row. Nine of its handlers ALSO took organization_id
    # as a required client-supplied query parameter: the IDOR shape, and a 422 for any
    # client that did not send it. Both now derive the org from the token.
    #
    # STILL OUTSTANDING there, deliberately: logistics_correlation declares
    # prefix="/logistics" and main.py mounts it at /api/v1/logistics, so its routes
    # serve at /api/v1/logistics/logistics/... — the double-prefix bug already fixed in
    # yard and transportation. Removing it collides with fleet_logistics.logistics_router
    # on /delivery-efficiency and /compliance/summary, which are the two paths the
    # frontend actually calls. Choosing which implementation is canonical is a product
    # decision, not a routing edit.
    "nlp_correlation.py": 7,
    # transportation.py is GONE from this list, and so is geotab.py.
    #
    # `get_vehicles` leaked outright: no organization filter, on a table with no RLS
    # to fall back on, so org A listed org B's fleet.
    #
    # The rest failed the OTHER way. `get_carriers`, `get_drivers`, `get_shipments`,
    # `get_routes` and `geotab.get_fleet_summary` took `organization_id` as a required
    # client-supplied query parameter — the IDOR shape — but their tables have ENABLE +
    # FORCE row-level security, and the handlers set no tenant GUC. The policy
    # therefore filtered every row: those endpoints returned an empty list to every
    # caller, including for its own organization. Verified against a real database.
    #
    # One wrong dependency, two opposite failure modes, decided only by whether the
    # table happened to carry a policy. Pinned by
    # tests/test_vehicle_tenant_isolation_realdb.py and
    # tests/test_transportation_tenant_scoping_realdb.py.
}


def _rls_tables() -> set[str]:
    tables: set[str] = set()
    pattern = re.compile(
        r"ALTER\s+TABLE\s+(\w+)\s+(?:FORCE\s+)?(?:ENABLE\s+)?ROW\s+LEVEL\s+SECURITY",
        re.I,
    )
    for sql in MIGRATIONS.glob("*.sql"):
        tables.update(m.group(1) for m in pattern.finditer(sql.read_text()))
    return tables


def _model_to_table() -> dict[str, str]:
    src = MODELS.read_text()
    return {
        m.group(1): m.group(2)
        for m in re.finditer(
            r'class (\w+)\(Base\):.*?__tablename__\s*=\s*[\'"](\w+)[\'"]', src, re.S
        )
    }


def _offenders() -> dict[str, int]:
    """Routers using get_db that reference a model backed by an RLS table."""
    rls = _rls_tables()
    models = _model_to_table()
    found: dict[str, int] = {}
    for path in sorted(API_DIR.glob("*.py")):
        if path.name in NO_USER_CONTEXT:
            continue
        text = path.read_text()
        count = text.count("Depends(get_db)")
        if not count:
            continue
        touches_rls = any(
            models[cls] in rls and re.search(rf"\b{cls}\b", text) for cls in models
        )
        if touches_rls:
            found[path.name] = count
    return found


def test_rls_tables_are_actually_detected():
    """Sanity: the guard is only meaningful if it finds the RLS tables."""
    tables = _rls_tables()
    assert "assets" in tables and "audit_logs" in tables, sorted(tables)[:10]
    assert len(tables) > 20, f"suspiciously few RLS tables found: {len(tables)}"


def test_no_new_get_db_on_rls_tables():
    """No router may newly read an RLS-protected table through get_db."""
    offenders = _offenders()
    new = {k: v for k, v in offenders.items() if k not in KNOWN_GET_DB_ON_RLS}
    assert not new, (
        "These routers query RLS-protected tables via get_db, which silently "
        "returns ZERO rows (no error). Use get_tenant_db + get_tenant_org_id:\n  "
        + "\n  ".join(f"{k} ({v} sites)" for k, v in sorted(new.items()))
    )


def test_known_debt_list_is_not_stale():
    """A router fixed (or shrunk) must be updated here, or the list becomes a lie."""
    offenders = _offenders()
    fixed = sorted(set(KNOWN_GET_DB_ON_RLS) - set(offenders))
    assert not fixed, (
        "These routers no longer use get_db on RLS tables — remove them from "
        f"KNOWN_GET_DB_ON_RLS: {fixed}"
    )
    shrunk = {
        k: (KNOWN_GET_DB_ON_RLS[k], offenders[k])
        for k in KNOWN_GET_DB_ON_RLS
        if k in offenders and offenders[k] < KNOWN_GET_DB_ON_RLS[k]
    }
    assert not shrunk, (
        "get_db sites were removed without updating the pinned counts "
        f"(name: expected -> actual): {shrunk}"
    )


@pytest.mark.parametrize("router", sorted(NO_USER_CONTEXT))
def test_exempt_routers_really_have_no_user_dependency(router: str):
    """The exemptions must stay justified — not a place to hide new debt.

    Each exempt router must authenticate by something other than a user
    (agent certificate, or nothing at all for infra probes).
    """
    text = (API_DIR / router).read_text()
    assert "get_current_active_user" not in text or "require_agent" in text, (
        f"{router} is exempt from the tenant-session guard but depends on an "
        "authenticated user — it should use get_tenant_db instead."
    )
