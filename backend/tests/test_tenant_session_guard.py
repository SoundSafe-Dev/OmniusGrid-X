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
}
# NOTE: health.py was initially exempted as "infra probes", but it is a MIXED
# file — /health/ready and /health/startup are unauthenticated probes while
# /health/detailed is admin-gated and counts Assets/Alarms. A blanket exemption
# would have hidden that second half, so it is listed as debt below instead.

# Known debt: routers still reading RLS-protected tables through `get_db`.
# The number is how many `Depends(get_db)` sites that router has — pinned so a
# partial fix still moves, and so nothing silently grows.
KNOWN_GET_DB_ON_RLS: dict[str, int] = {
    "analysis_sessions.py": 22,
    # Mixed: unauthenticated probes + an admin-gated view that reads Asset/Alarm.
    # Splitting the two is a change to the probe contract, so it is left for a
    # dedicated pass rather than bundled here.
    "health.py": 5,
    "audit.py": 5,
    "commands.py": 1,
    "erp_webhooks.py": 1,
    # fleet_logistics.py is GONE from this list. All 23 handlers moved to
    # get_tenant_db, and the four tables that have no RLS to fall back on
    # (geofence_zones, geofence_alerts, maintenance_schedules, repair_orders) are
    # now filtered explicitly via `_scope`. It was not merely on the wrong
    # dependency: the zone list returned every tenant's zones, and fetch-by-id was
    # a full IDOR — both confirmed against a real database. Its four create paths
    # also took organization_id from the client payload and now take it from the
    # token. Pinned by tests/test_fleet_logistics_tenant_isolation_realdb.py.
    "gdpr.py": 9,
    "kanban.py": 10,
    "logistics_correlation.py": 12,
    "nlp_correlation.py": 7,
    "platform_correlation.py": 1,
    # 24, not 25: `get_vehicles` moved to get_tenant_db. It was not merely on the
    # wrong dependency — it queried `vehicles` with NO organization filter, on a table
    # that has no RLS to fall back on, so org A listed org B's fleet. Confirmed against
    # a real database, fixed, and pinned by
    # tests/test_vehicle_tenant_isolation_realdb.py.
    #
    # The remaining 24 are NOT all benign: `get_carriers` and `get_drivers` take
    # `organization_id` as a client-supplied query parameter (the shape removed from
    # yard in migration-era FS work), and `get_carrier` fetches by id with no org check
    # at all. Those need the same treatment.
    "transportation.py": 24,
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
