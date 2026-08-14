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

import ast
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
    # 3, not 4. /admin/assets/{id}/maintenance was the fourth, and it was the worst of
    # them: it WROTE. `assets` is FORCE RLS, and under RLS an UPDATE is filtered rather
    # than rejected — it succeeds having matched no rows — so putting a machine into
    # maintenance returned 200 and changed nothing. (It never got that far in practice:
    # assets.maintenance_mode did not exist at all until migration 053, so the handler
    # 500'd on every call while the frontend went on calling it.) Now on get_tenant_db,
    # scoped to the caller's organisation, with the rowcount checked.
    # Pinned by tests/test_maintenance_mode_realdb.py.
    #
    # The remaining 3 sites are the UNAUTHENTICATED probes (/health/live, /ready,
    # /startup and their shared checks). They cannot use get_tenant_db, which resolves
    # a tenant from a user they do not have, so they read only tables without a policy
    # — which is why _check_ingestion had to drop its assets.last_seen read. They are
    # exempt in substance but stay counted here so the number cannot drift unnoticed.
    # Pinned by tests/test_admin_system_status_scoping_realdb.py.
    "health.py": 3,
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
    # must span organizations by construction.
    #
    # THIS COMMENT WAS STALE AND SAID "it is nonetheless BROKEN" (corrected 2026-08-01).
    # That was true when written: integration_configurations is FORCE RLS, the candidate
    # lookup returned nothing, and every inbound webhook was rejected 404. It was FIXED by
    # migration 052, which adds `webhook_tenant_resolution` — SELECT only, active ERP rows
    # only, only while `app.erp_webhook_lookup = 'on'`, a GUC the handler sets
    # transaction-locally and clears in a `finally`. Pinned by
    # tests/test_erp_webhook_tenant_resolution_realdb.py (12 tests, including that the flag
    # permits no writes and that nothing is visible without it).
    #
    # docs/engineering/defect-class-sweeps.md already said "Fixed by migration 052" — so
    # this comment contradicted the document it cites, and a reader trusting the guard over
    # the doc would have re-planned work that was done. Guard prose is documentation and
    # goes stale like any other.
    # fleet_logistics.py is GONE from this list. All 23 handlers moved to
    # get_tenant_db, and the four tables that have no RLS to fall back on
    # (geofence_zones, geofence_alerts, maintenance_schedules, repair_orders) are
    # now filtered explicitly via `_scope`. It was not merely on the wrong
    # dependency: the zone list returned every tenant's zones, and fetch-by-id was
    # a full IDOR — both confirmed against a real database. Its four create paths
    # also took organization_id from the client payload and now take it from the
    # token. Pinned by tests/test_fleet_logistics_tenant_isolation_realdb.py.
    # kanban.py and nlp_correlation.py are GONE from this list (FS-431). Seventeen handlers
    # between them, on tables that all have FORCE ROW LEVEL SECURITY.
    #
    # WHAT THE DEBT ENTRY UNDERSTATED. Four of the ten allowlisted 5xx endpoints traced here
    # and were fixed by the swap, as recorded. The other THIRTEEN handlers were never probed
    # by any walk, so nothing recorded what they were doing: reading zero rows and answering
    # 200. `list_task_rules` filters on organization_id itself, which changes nothing —
    # RLS removes the row before the filter sees it — so the automation-rules screen showed
    # an empty list to every tenant that had rules, and creating one was refused.
    #
    # `execute_completion_actions` came with them. It runs outside a request, so no
    # dependency binds the GUC; it now sets `app.current_org_id` itself from the
    # organization_id it was already being passed. Until then every completion action on
    # every task silently did not happen, on a code path that exists only for side effects.
    # logistics_correlation.py and platform_correlation.py are GONE from this list.
    # Both queried RLS-protected tables (dock_appointments, analysis_sessions) through
    # get_db, so every endpoint returned an empty result — logistics_correlation even
    # filtered on organization_id correctly itself, which made no difference because
    # RLS had already removed the row. Nine of its handlers ALSO took organization_id
    # as a required client-supplied query parameter: the IDOR shape, and a 422 for any
    # client that did not send it. Both now derive the org from the token.
    #
    # CLOSED (FS-468): logistics_correlation used to declare prefix="/logistics" while
    # main.py mounted it at /api/v1/logistics, so its routes served at
    # /api/v1/logistics/logistics/... The blocker was never the edit — it was that
    # dropping the prefix collided with fleet_logistics.logistics_router on
    # /delivery-efficiency and /compliance/summary. fleet_logistics is canonical for
    # those two (response models, the HOS compliance fix, and the paths the frontend
    # calls); the correlation variants moved under /correlation/.
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


#: `ALTER TABLE assets ENABLE ROW LEVEL SECURITY` — the literal form.
_LITERAL_RLS = re.compile(
    r"ALTER\s+TABLE\s+(\w+)\s+(?:FORCE\s+)?(?:ENABLE\s+)?ROW\s+LEVEL\s+SECURITY",
    re.I,
)
#: `EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t)` driven by a
#: `FOREACH t IN ARRAY ARRAY['a', 'b', ...]` loop — the form migration 052 uses.
_DYNAMIC_RLS = re.compile(
    r"format\(\s*'ALTER TABLE %I[^']*ROW LEVEL SECURITY", re.I
)
_ARRAY_LITERAL = re.compile(r"ARRAY\s*\[([^\]]+)\]", re.S)


def _rls_tables() -> set[str]:
    """Tables under RLS, per the migration chain.

    MUST UNDERSTAND BOTH FORMS. This used to match only the literal
    `ALTER TABLE <name> ...`, and migration 051 enables RLS through
    `EXECUTE format('ALTER TABLE %I ...', t)` over a table array. The four tables it
    protects — geofence_zones, geofence_alerts, maintenance_schedules, repair_orders —
    were therefore invisible here: the guard believed they had no policy, so a router
    using `get_db` on any of them would not have been flagged, and the protection added
    for them was invisible to the tool that enforces the pattern.

    Parsing SQL text is a proxy for asking the database, and this is the cost of the
    proxy. It stays static so the check remains in the fast suite; the regression is
    pinned by `test_dynamically_enabled_rls_is_detected`.
    """
    tables: set[str] = set()
    for sql in MIGRATIONS.glob("*.sql"):
        text = sql.read_text()
        tables.update(m.group(1) for m in _LITERAL_RLS.finditer(text))
        if _DYNAMIC_RLS.search(text):
            for block in _ARRAY_LITERAL.findall(text):
                tables.update(re.findall(r"'(\w+)'", block))
    return tables


def _model_to_table() -> dict[str, str]:
    src = MODELS.read_text()
    return {
        m.group(1): m.group(2)
        for m in re.finditer(
            r'class (\w+)\(Base\):.*?__tablename__\s*=\s*[\'"](\w+)[\'"]', src, re.S
        )
    }


#: PROSE IS NOT CODE (FS-431). This counted `Depends(get_db)` in the RAW source, so a
#: comment or docstring EXPLAINING that a handler no longer takes the unscoped session was
#: counted as a handler that does. kanban.py reported one remaining offender after all ten
#: were fixed, and the offender was a sentence saying so.
#:
#: It fools the guard in the direction that keeps a file on the debt list forever, which is
#: the safe direction and therefore the one nobody would notice. `test_capped_lists_cannot_
#: grow`, `test_capped_lists_are_ordered` and `test_frontend_body_fields_are_declared` each
#: learned this separately; it is the fourth time in this directory.
_DOCSTRING = re.compile(r'("""|\'\'\')(?:.|\n)*?\1')
_COMMENT = re.compile(r"#[^\n]*")


def _code_only(source: str) -> str:
    return _COMMENT.sub("", _DOCSTRING.sub("", source))


#: `from app.api.<module> import <names>` — a router borrowing another router's helper.
_API_IMPORT = re.compile(r"^from app\.api\.(\w+) import ([^\n(]+|\([^)]*\))", re.M)


def _names_rls_model(text: str, models: dict[str, str], rls: set[str]) -> bool:
    return any(models[cls] in rls and re.search(rf"\b{cls}\b", text) for cls in models)


def _reaches_rls(name: str, text: str, models, rls, seen=frozenset()) -> bool:
    """Does this router query an RLS table — ITSELF, or through a helper it imports from
    another router?

    THE SECOND HALF WAS THE BLIND SPOT, and it cost two live endpoints (FS-718).
    `operations_assistant.py` took `Depends(get_db)` and named no model at all: it hands the
    session to `_execute_evidence_request`, which lives in `correlation_evidence.py` and
    reads `intake_items` (FORCE RLS). By the file-local rule this router touched nothing, so
    it was never a candidate — and `POST /operations/answer` and `POST /operations/briefing`
    answered **404 on the caller's own uploads**, in the exact fail-quiet shape this guard
    was written for.

    A router that imports another router's helper is presumed to reach whatever that helper
    reaches. That is deliberately generous: passing an unscoped session across a module
    boundary is the thing being checked, and the cost of a false positive is one
    `get_tenant_db`, while the cost of a false negative is silent tenant-wide emptiness.

    One hop, cycle-guarded. Two routers importing from each other resolve rather than recur.
    """
    if _names_rls_model(text, models, rls):
        return True
    if name in seen:
        return False
    for match in _API_IMPORT.finditer(text):
        module = match.group(1)
        other = API_DIR / f"{module}.py"
        if not other.exists() or module in seen:
            continue
        imported = re.findall(r"\w+", match.group(2))
        other_text = _code_only(other.read_text())
        # Only if the borrowed name is actually CALLED here — an import that is re-exported
        # or used in a type annotation moves no session.
        if not any(re.search(rf"\b{n}\s*\(", text) for n in imported):
            continue
        if _reaches_rls(module, other_text, models, rls, seen | {name, module}):
            return True
    return False


def _offenders() -> dict[str, int]:
    """Routers using get_db that reach a model backed by an RLS table."""
    rls = _rls_tables()
    models = _model_to_table()
    found: dict[str, int] = {}
    for path in sorted(API_DIR.glob("*.py")):
        if path.name in NO_USER_CONTEXT:
            continue
        text = _code_only(path.read_text())
        count = text.count("Depends(get_db)")
        if not count:
            continue
        if _reaches_rls(path.stem, text, models, rls):
            found[path.name] = count
    return found


def test_rls_tables_are_actually_detected():
    """Sanity: the guard is only meaningful if it finds the RLS tables."""
    tables = _rls_tables()
    assert "assets" in tables and "audit_logs" in tables, sorted(tables)[:10]
    assert len(tables) > 20, f"suspiciously few RLS tables found: {len(tables)}"


def test_dynamically_enabled_rls_is_detected():
    """Migration 051 enables RLS through EXECUTE format(...) over a table array. If the
    parser stops seeing that form, these four silently drop out of the guard's view and
    a `get_db` regression on them would pass unnoticed."""
    tables = _rls_tables()
    for name in ("geofence_zones", "geofence_alerts", "maintenance_schedules",
                 "repair_orders"):
        assert name in tables, (
            f"{name} has RLS (migration 051) but the guard cannot see it — a router "
            f"using get_db on it would not be flagged"
        )


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


#: Handlers that build their own session instead of taking one as a dependency.
#: The guard used to look ONLY for `Depends(get_db)`, and its own notes on commands.py
#: said why that was not enough — "a static guard keyed on one idiom under-counts a file
#: that uses two". The idiom was named and never swept, and five more handlers were
#: sitting in the gap: three `/api/v1/oee/*` routes answering 404 for the caller's own
#: asset, plus `/health-index` and `/simulation/fleet-summary` reporting an empty fleet.
#: Pinned by `test_inline_session_tenant_scoping_realdb.py`.
INLINE_SESSION_ALLOWED: dict[str, str] = {
    # EMPTY as of 2026-08-04 (FS-431). Its one entry was kanban.py's
    # `execute_completion_actions`, held because "kanban RLS is an open ticket in another
    # lane". The ticket described four 5xx endpoints; the same root cause reached this
    # function too, and it took one `set_config` on the session it already opens using the
    # organization_id it was already given.
}


#: stem -> {function name: its source}. Built once per module; used to follow a call from a
#: background-task closure into the helper that actually queries.
_FUNC_SRC: dict[str, dict[str, str]] = {}


def _module_functions(stem: str) -> dict[str, str]:
    if stem in _FUNC_SRC:
        return _FUNC_SRC[stem]
    _FUNC_SRC[stem] = {}
    try:
        source = (API_DIR / f"{stem}.py").read_text()
        tree = ast.parse(source)
    except (OSError, SyntaxError):  # pragma: no cover - unparseable modules fail elsewhere
        return _FUNC_SRC[stem]
    _FUNC_SRC[stem] = {
        node.name: (ast.get_source_segment(source, node) or "")
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return _FUNC_SRC[stem]


def _body_reaches_rls(body, stem, models, rls, depth=0, seen=frozenset()) -> bool:
    """Does this FUNCTION reach an RLS table — itself, or through a helper it calls?

    THE CLOSURE THAT NAMED NOTHING (FS-718). `create_intake_evidence_job` opens its
    background session inside a nested `async def run(report)` whose whole body is a call to
    `_execute_evidence_request`. It names no model, so the body-local check cleared it — and
    the session it built was `AsyncSessionLocal()`, with no GUC, against `intake_items`
    under FORCE RLS. **Every asynchronous evidence job failed**, reporting an error that
    reads as "the caller passed ids that do not exist".

    A background task is exactly where this hides: it has no request to take a dependency
    from, so it builds its own session, and the query is always somewhere else.
    """
    if _names_rls_model(body, models, rls):
        return True
    if depth > 2:
        return False
    calls = set(re.findall(r"\b(\w+)\s*\(", body))
    local = _module_functions(stem)
    for name in calls & set(local):
        if (stem, name) in seen:
            continue
        if _body_reaches_rls(local[name], stem, models, rls, depth + 1, seen | {(stem, name)}):
            return True
    module_source = _code_only((API_DIR / f"{stem}.py").read_text())
    for match in _API_IMPORT.finditer(module_source):
        other = match.group(1)
        for name in set(re.findall(r"\w+", match.group(2))) & calls:
            fns = _module_functions(other)
            if name in fns and (other, name) not in seen:
                if _body_reaches_rls(
                    fns[name], other, models, rls, depth + 1, seen | {(other, name)}
                ):
                    return True
    return False


def _binds_tenant(body: str, stem: str) -> bool:
    """Does this function bind a tenant — itself, or through a helper it calls?

    Setting the GUC by hand is a legitimate alternative to `get_tenant_db`; the ingestion
    worker and the audit writers do it. `erp_integrations.run_erp_sync` does it too, but
    through `_set_tenant_guc(db, organization_id)` — the same extraction any file makes once
    it does this twice — so the literal `current_org_id` lives in the helper, not the caller.

    Recognising only the inline spelling would have reported that function as unscoped when
    it is scoped, and the natural way to silence a false positive is to add an exemption,
    which is how a guard loses the ability to see the real thing.
    """
    if "current_org_id" in body or "tenant_session(" in body:
        return True
    local = _module_functions(stem)
    for name in set(re.findall(r"\b(\w+)\s*\(", body)) & set(local):
        if "current_org_id" in _code_only(local[name]):
            return True
    return False


def _inline_session_offenders() -> dict[str, list[str]]:
    """file -> handlers that open AsyncSessionLocal, touch an RLS model, bind no tenant."""
    rls = _rls_tables()
    models = _model_to_table()
    found: dict[str, list[str]] = {}
    for path in sorted(API_DIR.glob("*.py")):
        if path.name in NO_USER_CONTEXT or path.name in INLINE_SESSION_ALLOWED:
            continue
        source = path.read_text()
        if "AsyncSessionLocal(" not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # `_code_only`, NOT the raw segment. THIS IS FS-431 A SECOND TIME, in the
            # other half of the same file: the `Depends(get_db)` sweep above learned that a
            # comment explaining the pattern reads as the pattern, and this half was never
            # given the same treatment. It cost a real mutation test — reverting the
            # FS-718 job fix left behind a comment saying why the GUC matters, the word
            # `current_org_id` appeared in the body, and the guard exempted the very
            # function whose session had no GUC at all. A guard a comment can satisfy is a
            # guard whose result depends on prose.
            body = _code_only(ast.get_source_segment(source, node) or "")
            if "AsyncSessionLocal(" not in body:
                continue
            if _binds_tenant(body, path.stem):
                continue
            if _body_reaches_rls(body, path.stem, models, rls):
                found.setdefault(path.name, []).append(node.name)
    return found


def test_no_handler_opens_an_unbound_session_on_an_rls_table():
    """The second idiom. `AsyncSessionLocal()` sets no `app.current_org_id`, so an
    RLS-protected read through it matches nothing — the handler 404s on rows the caller
    owns, or answers 200 with an empty list. Either take `Depends(get_tenant_db)`, or
    set the GUC explicitly the way the ingestion worker does."""
    offenders = _inline_session_offenders()
    assert not offenders, (
        "These open their own session, read an RLS-protected model, and bind no tenant:\n  "
        + "\n  ".join(f"{f}: {', '.join(fns)}" for f, fns in sorted(offenders.items()))
    )


def test_every_inline_exemption_states_a_reason():
    """A filename on an allowlist explains nothing, and a silent allowlist is how debt
    becomes permanent. The reason is what lets the next reader decide whether it still
    applies."""
    for name, reason in INLINE_SESSION_ALLOWED.items():
        assert len(reason) > 40, f"{name} is exempted with no real reason"


def test_exemptions_are_not_stale():
    """The other direction: an entry for a file that no longer offends is a claim about
    debt that has already been paid, and it hides the next regression in that file."""
    rls = _rls_tables()
    models = _model_to_table()
    for name in INLINE_SESSION_ALLOWED:
        path = API_DIR / name
        if not path.exists():
            continue
        source = path.read_text()
        still = "AsyncSessionLocal(" in source and any(
            models[cls] in rls and re.search(rf"\b{cls}\b", source) for cls in models
        )
        assert still, (
            f"{name} no longer opens an unbound session on an RLS model — drop it from "
            f"INLINE_SESSION_ALLOWED so the guard covers it again"
        )


def test_the_inline_sweep_can_see_the_idiom():
    """Vacuity: if the AST walk or the model map breaks, the check above passes while
    inspecting nothing — the failure mode this whole file exists to prevent."""
    rls = _rls_tables()
    models = _model_to_table()
    assert models, "no models parsed; the inline sweep would find nothing"
    assert any(t in rls for t in models.values()), "no model maps to an RLS table"
    users = [p for p in API_DIR.glob("*.py") if "AsyncSessionLocal(" in p.read_text()]
    assert users, (
        "no API module opens AsyncSessionLocal any more; if that is real, delete this "
        "check rather than leaving one that can never fire"
    )
