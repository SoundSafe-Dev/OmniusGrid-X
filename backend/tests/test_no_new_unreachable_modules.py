"""7,726 lines of backend that nothing imports. This stops it growing.

Eighteen modules under `app/` are referenced by no other module, no test, no script and no
edge-agent file. Some are a missing wiring layer; some are dead weight. **Both are decisions,
and the point of this file is that they get made rather than accumulate.**

WHY NOT JUST DELETE THEM. Several sit inside somebody else's open work — `#37` asks whether ERP
data belongs on Kafka at all, which is exactly what `kafka_connect_integration` would answer,
and `#36` asks the same of `erp_database_replication`. Deleting them would preempt a decision
that is somebody's assigned task. So the baseline records each with its reason, and the
assertion is that **nothing new joins the list**.

WHAT UNREACHABLE COSTS, since it looks free. A module nothing imports is a module nothing
tests, nothing type-checks against real callers, and nothing updates when the schema moves — but
it reads as a feature to anybody browsing the tree, and it is the first thing somebody
"reuses" without discovering it never worked. `dynamics_data_extraction` and its three siblings
were found this way: 2,508 lines writing to `erp_sync_status` with a session they take as a
parameter, from callers that do not exist.

TWO BASELINE ENTRIES WERE ALREADY WRONG, and widening the walk is what showed it.
`oracle_correlation_patterns` is loaded by `erp_sync_correlation.PATTERN_CLASSES` and has been
routed since Oracle was wired; `infor_connector` is loaded by `erp_connector_factory`. Both are
imported **by string**, through `importlib`, so no `ast.Import` node exists anywhere and both
sat in this baseline described as dead — with a reason, written by somebody who checked. A
reader acting on either entry would have deleted a live, routed module.

That is the cost of a detector that knows one idiom: not a false alarm, which announces itself,
but a **false entry in a curated list**, which reads as verified. Removed, and the walk now
counts a dotted `app.*` string in production code as the import it is.

THE DETECTOR WAS WRONG FIRST, and by a lot. Counting `ast.ImportFrom(module=...)` alone reported
**57** modules, because `main.py` mounts routers with `from app.api import alarms, alarm_rules,
…` — which records `app.api`, not `app.api.alarms`. Every router in the tree looked dead. The
walk now also records `f"{node.module}.{alias.name}"` for each imported name, which takes it to
the real 18. A dead-code sweep that flags a third of the API is one nobody reads twice.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "app"

#: Every unreachable module, with why it is still here. An entry is a claim that somebody has
#: looked; "unused" is not a reason, it is the observation.
UNREACHABLE: dict[str, str] = {
    # --- ERP middleware: the whole package, 1,997 lines ----------------------------------
    "app/services/erp_middleware/kafka_connect_integration.py":
        "POOL #37 decides this. Whether ERP data belongs on the bus alongside telemetry is an "
        "architectural question, and deleting the implementation would preempt it.",
    "app/services/erp_middleware/rabbitmq_integration.py":
        "Same package as the Kafka one; the decision in #37 should cover all five together "
        "rather than leaving four orphans behind one answer.",
    "app/services/erp_middleware/azure_service_bus_integration.py":
        "Same package and same decision as the Kafka one (POOL #37). Five middleware "
        "transports were built speculatively; none is reachable and one answer covers all.",
    "app/services/erp_middleware/boomi_integration.py":
        "Same package and same decision as the Kafka one (POOL #37). An iPaaS connector with "
        "no caller — the integration seam it targets does not exist in this product yet.",
    "app/services/erp_middleware/mulesoft_integration.py":
        "Same package and same decision as the Kafka one (POOL #37). As with Boomi, this "
        "targets an integration seam the product does not currently have.",

    # --- ERP connectors that take a session from a caller that does not exist -------------
    "app/services/erp_connectors/dynamics_data_extraction.py":
        "Writes erp_sync_status from a `db` parameter; nothing supplies one. Migration 058's "
        "header records that these are not a reason to leave FORCE off, because if they are "
        "ever wired the caller has to bind the tenant like every other background writer.",
    "app/services/erp_connectors/oracle_data_extraction.py":
        "Same shape as dynamics_data_extraction: 575 lines writing erp_sync_status from a `db` "
        "parameter no caller supplies. The Oracle sync that ships goes through run_erp_sync.",
    "app/services/erp_connectors/sap_data_extraction.py":
        "Same shape as dynamics_data_extraction, and the most misleading of the three because "
        "SAP is the one vendor whose sync IS wired — through run_erp_sync, not this file.",
    "app/services/erp_connectors/sap_webhook_integration.py":
        "Superseded by `app/api/erp_webhooks.py` + `erp_webhook_receiver`, which is what the "
        "signed-webhook path actually uses. Delete candidate — but confirm no vendor-specific "
        "logic here is missing from the generic receiver first.",

    # --- other ---------------------------------------------------------------------------
    "app/services/erp_security.py":
        "483 lines of ERP-specific security helpers. The credential handling that ships is in "
        "`core/security.py` and `erp_connector_factory`; this is a parallel implementation, "
        "which is the shape rule 55 warns about — a copy diverges silently.",
    "app/services/erp_error_handler.py":
        "Carries the only TODO in `app/` ('Trigger alert (email, Slack, PagerDuty)'). Retry "
        "classification that DOES ship lives in `erp_retry_classification`, which is tested.",
    "app/services/device_provisioning.py":
        "465 lines. Edge enrolment ships through `api/edge_enroll.py` + `services/edge_ca.py`. "
        "Hridyansh's lane — do not delete without asking whether OTA needs it.",
    "app/services/schema_registry.py":
        "Telemetry schema validation. `workers/ingestion.py` validates inline instead.",
    "app/services/feature_extraction.py":
        "MLOps lane. Feature extraction for training; the training pipeline that ships is "
        "`model_training_pipeline`.",
    "app/workers/export_delivery.py":
        "A worker with no entry point. `services/export_delivery.py` (different file, same "
        "name) IS wired and tested — which is precisely why this one is easy to miss.",
}


def _referenced() -> set[str]:
    """Every module name any Python file in the repository refers to."""
    seen: set[str] = set()
    roots = [APP, ROOT / "tests", ROOT / "scripts", ROOT.parent / "edge-agent"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    seen.add(node.module)
                    # `from app.api import alarms` — WITHOUT this the walk reports 57 dead
                    # modules instead of 18, because every mounted router looks unreferenced.
                    for alias in node.names:
                        seen.add(f"{node.module}.{alias.name}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        seen.add(alias.name)
                # A DOTTED MODULE PATH IN A STRING IS AN IMPORT (FS-558..561).
                #
                # `erp_sync_correlation.PATTERN_CLASSES` maps a vendor to
                # `("app.services.erp_connectors.odoo_correlation_patterns", "Odoo…")` and
                # loads it with `importlib.import_module`. There is no `ast.Import` node
                # anywhere, so four live, routed, tested modules read as unreachable — and
                # the fix a reader would reach for is to DELETE them.
                #
                # This is the third form of the same lesson in this file's history: the
                # walk knew `ImportFrom(module=)`, learned `module.alias`, and did not know
                # that a registry-driven codebase imports by string. Any dynamically loaded
                # module was invisible to it.
                elif (
                    # PRODUCTION ONLY. A dotted string in a TEST is not a production
                    # reference, and the vacuity probe below names a fictional module in
                    # exactly this form — counting it made the probe reference itself and
                    # the scan report it as reachable.
                    # `!=`, NOT `is not`. `ROOT / "tests"` builds a NEW Path each time,
                    # so an identity comparison is always true and the exclusion never
                    # applied — the probe below kept counting itself.
                    root != ROOT / "tests"
                    and isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.startswith("app.")
                    and "." in node.value[4:]
                ):
                    seen.add(node.value)
    return seen


def _unreachable() -> list[str]:
    referenced = _referenced()
    out = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        dotted = str(path.relative_to(ROOT).with_suffix("")).replace("/", ".")
        if dotted not in referenced:
            out.append(str(path.relative_to(ROOT)))
    return out


class TestTheScanIsNotVacuous:
    def test_it_sees_the_modules_that_ARE_reachable(self):
        """`app/main.py` imports every router. If the walk broke, everything would look
        unreachable and the baseline would swallow it."""
        unreachable = set(_unreachable())
        for reachable in (
            "app/api/alarms.py",          # mounted via `from app.api import alarms`
            "app/core/tenant.py",         # imported directly by many modules
            "app/services/oee_calculator.py",
        ):
            assert reachable not in unreachable, (
                f"{reachable} is reachable and the scan says otherwise — the walk is broken"
            )

    def test_it_would_report_a_new_orphan(self):
        """The positive control. A module named by nothing must be reported, or this file is
        a list rather than a guard."""
        referenced = _referenced()
        assert "app.services.a_module_that_does_not_exist" not in referenced

    def test_the_baseline_is_substantial(self):
        assert len(UNREACHABLE) > 10, "the baseline has been gutted rather than worked down"


class TestTheDeadSurfaceDoesNotGrow:
    def test_no_new_unreachable_module(self):
        """THE ASSERTION THIS FILE EXISTS FOR. A module nothing imports is a module nothing
        tests and nothing updates, and it reads as a feature to anybody browsing the tree."""
        new = sorted(set(_unreachable()) - set(UNREACHABLE))
        assert not new, (
            f"these modules are referenced by nothing: {new}.\n"
            "Wire them up, delete them, or add an entry saying who decides and when. "
            "'Unused' is the observation, not the reason."
        )

    def test_the_baseline_names_nothing_that_is_now_reachable(self):
        """Shrinking is the good direction, and a baseline that lists a module somebody has
        since wired up is one nobody trusts."""
        wired = sorted(set(UNREACHABLE) - set(_unreachable()))
        assert not wired, (
            f"these are in the baseline and are now referenced; remove them: {wired}"
        )

    def test_every_entry_says_who_decides_or_why(self):
        """An entry reading 'unused' is a gap with extra steps."""
        thin = [k for k, v in UNREACHABLE.items() if len(v) < 60]
        assert not thin, f"these entries do not say enough to act on: {thin}"
