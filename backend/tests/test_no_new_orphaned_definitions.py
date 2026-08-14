"""53 functions inside live modules that nothing calls. This stops it growing (FS-529).

`test_no_new_unreachable_modules.py` tracks whole **modules** nothing imports. It cannot see an
orphan inside a file that is imported and used every request — and that is the more dangerous
shape, because the module around it is alive, tested and reviewed, so the dead function inherits
all of that credibility.

WHAT THE INVENTORY FOUND, and the two that matter most:

  * **`core/security.py` holds a second, unreachable WebSocket authenticator.**
    `get_current_user_ws` has no callers; the live one is `api/auth.py:resolve_websocket_user`,
    whose own comment says *"Same checks as core.security.get_current_user_ws"* — it cites the
    dead one as its reference. They are not the same: the live one also handles the dev-token
    path. A parallel implementation of **authentication** is rule 55 in the worst possible
    place, and the next person to "reuse" the helper in `core/security` gets subtly different
    auth than the rest of the product.

  * **`llm_client.stream_generate` and `strategic_engine.get_recommendation_history`** are
    finished capability with no route in front of them. Not dead code — unwired features, and
    the reason two screens render `—`.

THE DETECTOR WAS WRONG FIRST, BY A FACTOR OF TWENTY. Its first run reported **1,111 of 1,936**
functions as orphaned — 57% of the codebase. The bug was a decrement: it subtracted one use per
`def`, on the theory that a definition is not a use. A definition produces no `Name` node for
itself, so nothing needed subtracting, and every method called exactly once netted to zero. A
sweep that flags most of a codebase is one nobody reads twice; the module-level guard's header
records being wrong the same way, by a factor of three.

Two more filters take it from 484 to 53, and both are real rather than convenient:

  * **Decorated functions are excluded.** A route handler, a pydantic validator, a
    `@lru_cache`d helper and a pytest fixture are all invoked by name-free machinery. Counting
    them would flag every endpoint in the product.
  * **Definitions inside already-unreachable modules are excluded.** They are counted once, by
    the module guard, and double-listing them here would make this file look like it had found
    twice as much.
"""

from __future__ import annotations

import ast
import collections
import functools
import pathlib

import pytest

from tests.test_no_new_unreachable_modules import UNREACHABLE as UNREACHABLE_MODULES

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "app"

#: Names invoked by a framework through a protocol rather than by a caller. Excluded because
#: flagging them is noise, and noise is what stops a sweep being read.
FRAMEWORK_PROTOCOL_NAMES = {
    # SQLAlchemy TypeDecorator: called by the dialect, never by name.
    "load_dialect_impl", "process_bind_param", "process_result_value",
    # http.server.BaseHTTPRequestHandler dispatches by method name.
    "do_GET", "do_POST", "do_HEAD",
}

#: Every orphan in a LIVE module, with what it is. An entry is a claim somebody looked.
#: "Unused" is the observation, not the reason.
ORPHANS: dict[str, str] = {
    # --- superseded parallel implementations, the dangerous ones --------------------------
    # ARRIVED WITH THE 2026-08-08 MERGE. Both are helpers for a path that was not finished,
    # in modules that ARE live — so they inherit the module's credibility while running
    # never, which is exactly the shape this file exists to name.
    "app/services/fleet_targeting.py::_membership_exists":
        "A bulk membership pre-check. The bulk-assignment route validates per row instead, "
        "so this never runs — and wiring it would replace four round trips with one, which "
        "is the reason to decide rather than delete.",
    "app/services/maintenance_windows.py::local_date_for_weekday":
        "Resolves a weekday to a local date inside a window's own timezone. The scheduler "
        "works in fixed UTC offsets today, which is what makes a DST boundary interesting; "
        "this helper is the half of that fix that landed.",
    "app/core/security.py::verify_token":
        "A thin wrapper over decode_local_token with no callers. Harmless in itself and part "
        "of the same duplicate-auth surface as get_current_user_ws — decide both together.",

    # --- finished capability with no route in front of it --------------------------------
    "app/services/llm_client.py::stream_generate":
        "Streaming answer generation, complete and unexposed. FS-563 is the route. Not dead "
        "code — an unwired feature.",
    # get_recommendation_history CAME OFF THIS LIST when FS-567 gave it a route
    # (GET /engines/strategic/recommendations/history). The staleness test named it on the
    # next full run — the inventory reporting a wired method as dead is the failure that
    # makes the whole list untrustworthy, so it is caught rather than curated.
    "app/services/tactical_engine.py::queue_inference":
        "Belongs to the tactical loop that main.py never starts (FS-530). Reachable the day "
        "that decision is made; meaningless before it.",
    "app/services/yard_management.py::find_optimal_dock":
        "Dock assignment optimisation. The live path assigns by explicit door id "
        "(POST /yard/dock/doors/{door}/assign/{trailer}); nothing chooses a door for you.",
    # --- ARRIVED WITH THE CORRELATION-ENGINE MERGE (2026-08-14) --------------------------
    # Five definitions, none of them a missing wire. Each was read before being listed.
    "app/services/multi_spreadsheet_correlator.py::enrich_asset_trends":
        "Enriches `asset_trends` — a list this module now DELIBERATELY leaves empty. The "
        "comment above its producer records why: attributing a file-level downtime total to "
        "every asset named in the file produced a convincing but false trend, so entity "
        "trends moved to the lineage-preserving evidence engine. This is the enricher for "
        "the behaviour that was removed. Wiring it would restore the false attribution.",
    "app/services/correlation_evaluation.py::assess_action_approval":
        "A two-line convenience wrapper over `ApprovalPolicyService().assess`. Callers use "
        "the service directly, which is the path the approval tests drive.",
    "app/services/operational_normalization.py::normalize_rows":
        "The plural of `normalize_row`, which IS live. A list comprehension with a docstring; "
        "callers iterate themselves because they interleave per-row error handling.",
    "app/services/ingestion_adapters.py::set_legacy_doc_converter":
        "An injection seam, twin of `set_ocr_adapter` beside it — that one has a test that "
        "swaps in a fake, this one does not yet. The asymmetry is the finding: legacy-doc "
        "conversion is the branch with no test double.",
    "app/services/operations_question_service.py::_row_matches_fields":
        "Private row filter. The question path filters through the normalized evidence rows "
        "instead, so this predicate never sees a row.",

    "app/services/erp_webhook_receiver.py::replay_event":
        "Replay for a stored webhook event. The DLQ surface it belongs to is itself "
        "unreachable (erp_error_handler, module guard).",
    "app/services/logistics_correlation_engine.py::analyze_with_ai":
        "AI-backed correlation analysis; the served path uses the deterministic one.",
    "app/services/correlation_ai_engine.py::validate_scenario":
        "Scenario validation with no caller in the intake path.",
    "app/services/correlation_ai_engine.py::_format_action_plan_item":
        "Private formatter; its caller was refactored away and left it.",
    "app/services/data_shedding.py::reset_stats":
        "Test/ops affordance with no test and no ops route calling it.",

    # --- ERP vendor methods the factory's route table does not reach ---------------------
    # These are Wave O's subject: five vendors have working connectors and no correlation
    # route (`route_for()` returns None), so their fetch methods have no caller by design
    # until that lands. Listed rather than deleted for exactly that reason.
    "app/services/erp_connectors/netsuite_connector.py::fetch_sales_orders": "FS-557 netsuite.",
    "app/services/erp_connectors/netsuite_connector.py::fetch_customers": "FS-557 netsuite.",
    "app/services/erp_connectors/odoo_connector.py::fetch_sales_orders": "FS-558 odoo.",
    "app/services/erp_connectors/odoo_connector.py::fetch_customers": "FS-558 odoo.",
    "app/services/erp_connectors/epicor_connector.py::fetch_parts": "FS-560 epicor.",
    "app/services/erp_connectors/epicor_connector.py::fetch_jobs": "FS-560 epicor.",
    "app/services/erp_connectors/dynamics_connector.py::fetch_contacts":
        "Dynamics is wired for correlation; these three entity fetches are not in its route.",
    "app/services/erp_connectors/dynamics_connector.py::fetch_opportunities": "As above.",
    "app/services/erp_connectors/dynamics_connector.py::fetch_tasks": "As above.",
    "app/services/erp_connectors/oracle_connector.py::bulk_import":
        "Bulk path; the live sync uses the paged fetch.",
    "app/services/erp_connectors/sap_connector.py::fetch_with_delta":
        "Delta sync; run_erp_sync does a full fetch.",
    "app/services/erp_connectors/sap_connector.py::batch_fetch": "As above.",
    "app/services/erp_connectors/dynamics_correlation_patterns.py::analyze_project_resource_correlation":
        "A pattern the dynamics route does not select.",
    # `oracle_correlation_patterns.py` — THE ENTRIES CAME BACK, and the round trip is the
    # point.
    #
    # They were here, then removed as double-listed: the module-level guard carried the whole
    # file, so `_orphans()` excluded it and the entries described nothing. That was correct
    # when written.
    #
    # It stopped being correct when FS-558..561 taught the module guard that a dotted string
    # in `PATTERN_CLASSES` is an import. Oracle has been routed all along; the module was
    # never dead, its baseline entry was wrong, and removing that entry moved the file OUT of
    # the module guard's population and INTO this one — where its three genuinely orphaned
    # analyzers belong. Nobody wrote them back; this guard failed on the next full run and
    # named all three.
    #
    # Two guards handing a finding to each other as the facts change is the behaviour worth
    # having. A finding that fell between them would have been invisible in exactly the way
    # both files exist to prevent.
    "app/services/erp_connectors/oracle_correlation_patterns.py::analyze_employee_correlation":
        "An Oracle HR pattern the route table does not select. Oracle IS routed — for "
        "invoices and shipments — so this is an unselected analyzer in a live module, not "
        "dead code in a dead one.",
    "app/services/erp_connectors/oracle_correlation_patterns.py::analyze_project_correlation":
        "As above: a project-correlation analyzer with no entity routed to it.",
    "app/services/erp_connectors/oracle_correlation_patterns.py::analyze_cash_flow_correlation":
        "As above, and per the route table's own note it takes a PERIOD rather than a "
        "record, so the router could not call it even if an entity were routed.",
    "app/services/erp_correlation_patterns.py::analyze_supply_chain_risk":
        "Three vertical-specific pattern analysers with no selector reaching them.",
    "app/services/erp_correlation_patterns.py::analyze_defense_manufacturing_correlation": "As above.",
    "app/services/erp_correlation_patterns.py::analyze_smart_factory_correlation": "As above.",
    "app/services/erp_data_transformer.py::load_field_mappings":
        "Mapping loader; the transformer uses its inline table.",
    "app/services/erp_data_transformer.py::validate_data_quality":
        "Quality validation with no caller on the sync path.",
    "app/services/erp_connector_base.py::log_request":
        "Base-class affordances no connector calls.",
    "app/services/erp_connector_base.py::validate_config": "As above.",
    "app/services/transportation_management.py::can_accept_load":
        "Carrier capacity check; nothing consults it before assigning a load.",

    # --- half-wired helpers inside live API files ----------------------------------------
    "app/api/analysis_sessions.py::_is_lightweight_chat":
        "A lightweight-chat fast path, written and never branched to. Both halves are here "
        "and neither is reachable, so the feature exists and does not run.",
    "app/api/analysis_sessions.py::_build_lightweight_chat_response": "The other half of the above.",
    "app/api/nlp_correlation.py::_safe_numeric_min":
        "Safe numeric helpers with no call site — the code they were written to protect "
        "still uses the unguarded form.",
    "app/api/nlp_correlation.py::_safe_numeric_max": "As above.",
    "app/api/api_keys.py::verify_api_key":
        "API-key verification with no caller. The dependency the routes use is elsewhere; "
        "same duplicate-auth-surface concern as core/security, and worth resolving with it.",

    # --- modules the module guard lists, whose orphans surface here too ------------------
    "app/services/erp_database_replication.py::_initialize_cdc_for_table":
        "Inside a module the module-level guard already carries; listed because the file is "
        "imported by a live one and so does not qualify as unreachable by that guard's rule.",
    "app/services/erp_database_replication.py::_replicate_table": "As above.",
    "app/services/erp_database_replication.py::get_replication_status": "As above.",
    "app/services/erp_database_replication.py::stop_replication": "As above.",
    "app/services/keycloak_service.py::get_token":
        "Keycloak SSO surface. `api/sso.py` uses a subset; these seven are the rest of the "
        "client and are reachable the day SSO is switched on.",
    "app/services/keycloak_service.py::get_user_info": "As above.",
    "app/services/keycloak_service.py::get_user_roles": "As above.",
    "app/services/keycloak_service.py::enable_mfa": "As above.",
    "app/services/keycloak_service.py::disable_mfa": "As above.",
    "app/services/keycloak_service.py::get_users_by_organization": "As above.",
    "app/services/keycloak_service.py::fetch_user_from_keycloak": "As above.",
}


@functools.lru_cache(maxsize=1)
def _orphans() -> frozenset[str]:
    """`path::name` for every undecorated function in a live module with no reference."""
    definitions: dict[str, list[tuple[str, bool]]] = collections.defaultdict(list)
    for path in sorted(APP.rglob("*.py")):
        relative = str(path.relative_to(ROOT))
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions[node.name].append((relative, bool(node.decorator_list)))

    used: collections.Counter = collections.Counter()
    for root in ("app", "tests", "scripts"):
        directory = ROOT / root
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
                continue
            for node in ast.walk(tree):
                # NOTE: no decrement for the definition itself. A `def` emits no Name node
                # for its own name, and subtracting one produced 1,111 false positives.
                if isinstance(node, ast.Name):
                    used[node.id] += 1
                elif isinstance(node, ast.Attribute):
                    used[node.attr] += 1
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        used[alias.name] += 1
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    # `getattr(obj, "name")` and router/handler registration by string.
                    used[node.value] += 1

    found = set()
    for name, sites in definitions.items():
        if used[name] or name.startswith("__") or name in FRAMEWORK_PROTOCOL_NAMES:
            continue
        for relative, decorated in sites:
            if decorated or relative in UNREACHABLE_MODULES:
                continue
            found.add(f"{relative}::{name}")
    return frozenset(found)


class TestTheDetectorIsCalibrated:
    def test_it_does_not_flag_most_of_the_codebase(self):
        """Its first version reported 1,111 of 1,936 functions — 57% — because it subtracted
        a use per definition. A sweep that flags most of a codebase is one nobody reads
        twice, and it would have hidden the two auth duplicates in the noise."""
        total = sum(
            1
            for path in APP.rglob("*.py")
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        found = _orphans()
        assert len(found) < total * 0.1, (
            f"{len(found)} of {total} definitions read as orphaned. Above about a tenth the "
            f"detector is broken, not the codebase."
        )

    def test_it_still_finds_something(self):
        assert _orphans(), (
            "no orphaned definitions at all. Either every one was resolved — worth "
            "celebrating and recording — or the walk broke and this gate is vacuous."
        )

    def test_a_route_handler_is_not_flagged(self):
        """Decorated functions are invoked by name-free machinery. Without that filter every
        endpoint in the product reads as dead."""
        found = _orphans()
        assert not any("app/api/health.py::health_check" in f for f in found)
        assert not any(f.endswith("::driver_safety") for f in found)


class TestNothingNewIsOrphaned:
    def test_no_definition_has_joined_the_list(self):
        new = sorted(_orphans() - set(ORPHANS))
        assert not new, (
            f"{new} are defined in a live module and referenced by nothing — not by app/, "
            f"not by tests/, not by scripts/. The module around them is imported and used, "
            f"so they inherit its credibility while running never. Wire it, delete it, or "
            f"add it to ORPHANS with what it actually is."
        )

    @pytest.mark.parametrize("entry", sorted(ORPHANS))
    def test_every_listed_definition_is_still_orphaned(self, entry: str):
        """A stale entry reports wired code as dead, and the next reader stops trusting the
        whole list — which FS-504 had just cost on a different allowlist."""
        path, _, name = entry.partition("::")
        if not (ROOT / path).exists():
            return  # deleted, one of the two acceptable outcomes
        source = (ROOT / path).read_text()
        if f"def {name}" not in source:
            return  # removed from the file, likewise
        assert entry in _orphans(), (
            f"{entry} has a caller now. Delete its entry — the decision it was holding open "
            f"has been made."
        )


class TestTheDuplicateAuthSurfaceIsNamed:
    """Called out separately from the inventory because it is the one place where "unused" is
    not the risk. Unreachable authenticators sat beside the live one, and the live one's own
    comment pointed at a dead one as its model.

    ONE OF THE THREE IS GONE, and gone the right way (2026-08-09). The merge made
    `api/auth.py:resolve_websocket_user` **delegate to** `core.security.get_current_user_ws`
    instead of reimplementing it — so there is now one WebSocket authenticator rather than
    two that differ, and the entry it held is deleted rather than reworded. That is what
    closing one of these looks like: the duplicate stops existing, not the record of it.
    """

    @pytest.mark.parametrize(
        "entry",
        [
            "app/core/security.py::verify_token",
            "app/api/api_keys.py::verify_api_key",
        ],
    )
    def test_the_reason_names_the_risk(self, entry: str):
        assert entry in ORPHANS, f"{entry} dropped out of the inventory"
        reason = ORPHANS[entry]
        assert "auth" in reason.lower() or "rule 55" in reason, (
            f"the entry for {entry} does not say why an unreachable AUTH helper is worse "
            f"than an unreachable formatter"
        )
