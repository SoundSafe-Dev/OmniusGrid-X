"""Guard against code that reports work it did not do (FS-235).

THE CLASS. `erp_correlation_patterns.create_registry_items_for_sap` built a list of
dicts, appended their item codes to `created_ids`, logged
`sap_registry_items_created` with a count, and returned — having written nothing.
Both live SAP webhook paths called it and believed registry items existed.

This is a worse failure than a crash or a silent no-op. A crash gets fixed. A
no-op that returns empty is at least detectable by the caller. A no-op that
*reports success with a count* actively misleads: the logs say it worked, metrics
built on those logs say it worked, and an operator reading them has no reason to
look.

WHAT THIS FILE DOES. Two complementary checks:

  * a STATIC scan for the shape — a function that logs a `*_created` / `*_synced` /
    `*_sent` style event while containing no write to the database. Pattern-based,
    so it catches instances nobody thought to write a case for.
  * EXPLICIT regression tests for the three known instances, so they cannot come
    back quietly even if the static scan is later weakened.

The static scan is deliberately narrow. It looks for a success event and the
absence of any persistence call in the same function — not for "correctness". It
will not catch a function that writes the wrong thing, and it is not meant to.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[1] / "app"

# Event-name suffixes that assert something was PERSISTED or DISPATCHED.
#
# `_updated` was in this list on the first run and had to come out: an in-memory
# state change (`websocket_manager.update_subscription`, `configure_retry`)
# legitimately logs `*_updated` and legitimately writes nothing. Keeping it would
# have meant exempting honest code to keep the gate quiet, which trains people to
# add exemptions rather than read them.
SUCCESS_SUFFIXES = ("_synced", "_sent", "_persisted", "_saved", "_created")

# Markers that make an event name a NEGATION, not a success claim. A suffix match
# alone fires on `..._rotated_but_not_persisted`, which is a warning stating that the
# work did NOT happen -- the precise opposite of the dishonesty this scans for.
#
# Found when the Intuit connector's "the rotated refresh token was NOT saved" warning
# was reported as a false success claim. Renaming the event to dodge the substring
# would have been the wrong fix: the next honest `..._not_saved` warning would trip
# it again, and the pressure would be to stop writing clear warnings.
NEGATION_MARKERS = ("_not_", "_never_", "_failed", "_unsaved", "_skipped", "_missing")

# Calls that constitute doing the work. `add` / `execute` / `commit` cover
# SQLAlchemy; `send`/`publish` cover Kafka and notifications; `record_audit` is the
# shared audit writer.
PERSISTENCE_CALLS = {
    # SQLAlchemy
    "add", "add_all", "execute", "commit", "flush", "merge", "delete",
    "merge_all", "bulk_save_objects", "save",
    # Brokers / HTTP / notifications
    "send", "send_and_wait", "publish", "post", "put", "patch", "request",
    # Filesystem — a write to disk is every bit as much "doing the work" as a database
    # write. (The original example here, `app/core/secrets.py`, was deleted in FS-748: it
    # was unreachable code whose Fernet cipher is not FIPS-approved, and dead code with
    # weak crypto is a trap for whoever wires it up next. The rule it illustrated stands.)
    "write", "writelines", "dump", "chmod",
    # The shared audit writer.
    "record_audit",
}

# Known-good exemptions, each with a reason. An exemption is a claim that the
# success event is honest despite no write in that function — usually because the
# write happens in a helper it calls.
EXEMPT: dict[str, str] = {
    # Logs after delegating the write to another awaited coroutine.
    "_process_correlation_analysis": "persists via _create_registry_item_from_analysis",
    # "created" here means an object was CONSTRUCTED, not persisted. A factory
    # returning a connector is not claiming a durable side effect, so the event is
    # honest even though nothing is written.
    "create_from_config": "constructs an in-memory connector; nothing to persist",
}


def _iter_functions():
    for path in sorted(SERVICES.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield path, node


def _logged_success_events(fn) -> list[str]:
    """Success-style event names this function logs."""
    events = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # logger.info("x_created", ...) / logger.warning(...)
        if not (isinstance(func, ast.Attribute) and func.attr in ("info", "warning", "error", "debug")):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if first.value.endswith(SUCCESS_SUFFIXES) and not any(
                marker in first.value for marker in NEGATION_MARKERS
            ):
                events.append(first.value)
    return events


def _does_work(fn) -> bool:
    """Does this function persist, dispatch, or delegate to something awaited?"""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in PERSISTENCE_CALLS:
                return True
        # An awaited call to another coroutine may do the write. Counting this
        # keeps the scan from flagging every orchestration function, at the cost
        # of missing a case where the delegate is itself a no-op — which is why
        # the explicit regression tests below exist.
        if isinstance(node, ast.Await):
            return True
    return False


class TestNoFunctionReportsWorkItDidNotDo:
    def test_static_scan(self):
        offenders = []
        for path, fn in _iter_functions():
            if fn.name in EXEMPT:
                continue
            events = _logged_success_events(fn)
            if not events:
                continue
            if not _does_work(fn):
                rel = path.relative_to(SERVICES.parent)
                offenders.append(f"{rel}:{fn.lineno} {fn.name}() logs {events} but performs no write")

        assert offenders == [], (
            "These functions report success without doing the work — the "
            "erp_correlation_patterns class (FS-231):\n  "
            + "\n  ".join(offenders)
            + "\n\nEither do the work, or log a failure/skip event instead. If the "
            "write genuinely happens elsewhere, add an EXEMPT entry with the reason."
        )


class TestKnownInstancesStayFixed:
    """Explicit regression tests for the three cases found in FS-231..233."""

    async def test_sap_registry_creation_reports_skip_not_success(self):
        """An unknown domain must log a SKIP and return [], not a success count.

        `"PROCUREMENT"` was the domain the old code's own branch handled, and it is
        not a key in DOMAIN_REGISTRY_MAPPING — so that branch was dead while the
        function still logged `sap_registry_items_created`.
        """
        from app.services.erp_correlation_patterns import ERPCorrelationPatterns

        patterns = ERPCorrelationPatterns("org-1", "int-1")
        result = await patterns.create_registry_items_for_sap(
            db=None, domain="PROCUREMENT", sap_data={}, organization_id="org-1"
        )
        assert result == [], "an unknown domain must return no ids"

    def test_sap_item_specs_cover_the_live_call_sites(self):
        """`PRODUCTION_OEE` and `MAINTENANCE` are the two domains the SAP webhook
        actually passes. PRODUCTION_OEE previously had NO branch, so it logged
        success with item_count=0."""
        from app.services.erp_correlation_patterns import ERPCorrelationPatterns

        patterns = ERPCorrelationPatterns("org-1", "int-1")
        for domain in ("PRODUCTION_OEE", "MAINTENANCE"):
            specs = patterns._sap_registry_item_specs(domain, {"order_number": "X1"})
            assert specs, f"{domain} is a live call site with no item template"

    async def test_erp_cdc_replication_refuses_instead_of_claiming_started(self):
        """It returned {"status": "replication_started"} and spawned infinite
        no-op polling loops over `pass` helpers."""
        from app.services.erp_database_replication import ERPDatabaseReplicationService

        service = ERPDatabaseReplicationService("org-1", "int-1", "SAP")
        with pytest.raises(NotImplementedError):
            await service.start_replication(db=None, tables=["t"], cdc_config={})

    async def test_replication_lag_monitoring_admits_it_does_not_exist(self):
        """The module docstring advertised "Replication lag monitoring". It was a
        `pass`, so ERP replication lag has never been measured."""
        from app.services.erp_database_replication import ERPDatabaseReplicationService

        service = ERPDatabaseReplicationService("org-1", "int-1", "SAP")
        with pytest.raises(NotImplementedError):
            await service._check_replication_lag(db=None, table="t")

    def test_simulated_geotab_payloads_declare_themselves(self):
        """HOS figures are DOT-regulated. A response carrying invented
        `drive_hours_today` must not be indistinguishable from a measured one.

        Renamed from `_simulated_provenance` to `simulated_provenance` in FS-267, when the
        exceptions ENVELOPE — built in `app/api/geotab.py`, not in the service — also
        needed to stamp itself.

        That sprint found the wider hole this assertion cannot see: the helper existed and
        was correct, and two of the four functions that refuse to run outside simulated
        mode never called it. Checking that the stamp is well-formed says nothing about
        whether it is applied. The pairing sweep lives in
        `tests/test_simulated_data_says_so.py`.
        """
        from app.services.geotab_service import simulated_provenance

        provenance = simulated_provenance()
        assert provenance["simulated"] is True
        assert "compliance" in provenance["warning"].lower()

    def test_simulated_hos_numbers_are_self_consistent(self):
        """`violations_today` used to be computed from the REAL
        `driver.hos_drive_hours_today` while every other field was random, so a
        response could report 11.9 drive hours and 0 violations. Plausible-looking
        but irreconcilable numbers are worse than obviously fake ones."""
        import inspect

        from app.services import geotab_service

        source = inspect.getsource(geotab_service.GeoTabService.get_driver_hos)
        # The flag must derive from the local values this response returns.
        assert "drive_hours > DRIVE_LIMIT" in source, (
            "violations_today must be derived from the hours in this response"
        )
        assert "driver.hos_drive_hours_today > 11" not in source, (
            "violations_today is again reading a different source than the hours "
            "it returns"
        )

    def test_oee_flags_unmeasured_quality_instead_of_claiming_100_percent(self):
        """An asset with no part counters must not report "Quality 100%".

        `quality` falls back to 1.0 by necessity — it is a multiplier in
        A x P x Q, and zeroing it would zero the OEE of every line without quality
        instrumentation. But 1.0 is a NEUTRAL VALUE, not a measurement, and the
        endpoint used to serve it as `"quality": 1.0` with nothing to distinguish it
        from a line that genuinely produced zero rejects.
        """
        import inspect

        from app.services import oee_calculator

        source = inspect.getsource(oee_calculator.OEECalculator.calculate_oee)
        assert "quality_measured = total_parts > 0" in source, (
            "quality must record whether it was measured, not just fall back to 1.0"
        )

        metrics = oee_calculator.OEEMetrics()
        assert hasattr(metrics, "quality_measured")
        assert hasattr(metrics, "performance_measured")
