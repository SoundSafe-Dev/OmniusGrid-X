"""Every background service is either started by `main.py` or recorded as dormant.

WHY THIS EXISTS. `tactical_engine` reported control commands it never sent, and the only
reason that never hurt anyone is that its `start()` is absent from `main.py` — a fact
recorded nowhere, discoverable only by grepping. A service that looks wired and is not is
exactly as misleading as a function that looks wired and is not, and it is harder to see:
nothing in the module says "this never runs".

So the split is written down and checked. A new singleton that nobody starts fails this
test; starting a dormant one without updating the record fails it too, which forces the
consequences to be considered rather than discovered.

WHAT DORMANT COSTS TODAY. Nothing, and that was verified rather than assumed: every
producer that queues into `cloud_gateway` — the one dormant service with an unbounded-ish
in-memory buffer — is itself dormant or unwired, so nothing accumulates in a queue no
`_flush_loop` is draining. If any of them is started WITHOUT starting `cloud_gateway`,
that stops being true immediately, which is the sharpest reason to make the set explicit.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Dict, List, Set, Tuple

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
MAIN = APP / "main.py"

#: Started by `main.py`'s lifespan. Growing this list is normal.
EXPECTED_STARTED: Set[str] = {
    "command_executor",
    "compliance_report_dispatcher",
    "error_tracker",
    "export_scheduler",
    "oee_calculator",
    #: FS-427. Drains the systems-of-record ledger per organisation on a timer, so a posting
    #: raised at 03:00 is attempted without anyone opening the Shop Floor page and pressing
    #: the button — which was the only thing that moved one.
    "posting_drain_scheduler",
    "report_scheduler",
    "rollout_orchestrator",
    #: FS-704. DB-backed refresh of the fleet liveness gauges: process-memory gauges die
    #: with the process, edge_agent_status.last_seen does not, so this is what lets an
    #: agent that died BEFORE a backend restart still fire EdgeAgentOffline after it.
    "edge_fleet_sweep",
}

#: Deliberately NOT started, with the reason. These are the edge-AI stack: they were
#: written to run beside a machine, not inside the cloud API process, and no process
#: currently runs them at all.
EXPECTED_DORMANT: Dict[str, str] = {
    "tactical_engine": (
        "Edge inference loop. Its dispatch refuses rather than pretending to send — see "
        "_dispatch_command — precisely because nothing starts it. Starting it without "
        "wiring a command sink would resume making control decisions that go nowhere."
    ),
    "strategic_engine": (
        "Cloud recommendation listener. main.py works around its absence explicitly: "
        "'Offline demo: the cloud strategic listener never connects, so seed a few…'."
    ),
    "cloud_gateway": (
        "Edge->cloud egress. Holds an in-memory list capped at 10,000 that sheds the "
        "oldest, drained only by the _flush_loop that start() launches. Harmless while "
        "every producer is also dormant; the moment one is started without this, queued "
        "events accumulate and are silently dropped."
    ),
    "egress_scheduler": (
        "Feature-vector egress loop (feature_extraction). Produces into cloud_gateway, "
        "so it must not be started before it."
    ),
    "mlops_pipeline": (
        "Model-registry polling loop. Also produces into cloud_gateway."
    ),
}

#: Producers whose output has nowhere to go unless cloud_gateway is running too.
CLOUD_GATEWAY_PRODUCERS = {"tactical_engine", "strategic_engine", "egress_scheduler", "mlops_pipeline"}


def _singletons() -> List[Tuple[str, str, bool]]:
    """(name, module, started) for every module-level object exposing `start()`."""
    main_source = MAIN.read_text()
    found: List[Tuple[str, str, bool]] = []
    for path in sorted(APP.glob("**/*.py")):
        if path.name == "main.py":
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # another test's problem
            continue
        with_start = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and any(
                isinstance(body, (ast.AsyncFunctionDef, ast.FunctionDef))
                and body.name == "start"
                for body in node.body
            )
        }
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                continue
            cls = getattr(node.value.func, "id", None)
            if cls in with_start and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                found.append((name, path.name, f"{name}.start()" in main_source))
    return found


SINGLETONS = _singletons()
STARTED = {n for n, _m, s in SINGLETONS if s}
DORMANT = {n for n, _m, s in SINGLETONS if not s}


class TestTheSweepIsNotVacuous:
    def test_it_discovers_the_singletons(self):
        assert len(SINGLETONS) >= 10, (
            f"only {len(SINGLETONS)} start()-bearing singletons found; the discovery is "
            f"broken and every assertion below would pass while checking nothing"
        )

    def test_both_states_are_represented(self):
        assert STARTED and DORMANT, (
            "the sweep sees only one state, so it cannot distinguish them"
        )


class TestTheLifecycleMatchesTheRecord:
    def test_no_service_is_silently_unwired(self):
        """A new singleton nobody starts. This is how `tactical_engine` came to report
        dispatches it never made without anyone noticing."""
        unexpected = sorted(DORMANT - set(EXPECTED_DORMANT))
        assert not unexpected, (
            "These services define start() and nothing calls it. Either wire them into "
            "main.py's lifespan, or add them to EXPECTED_DORMANT with the reason:\n  "
            + "\n  ".join(unexpected)
        )

    def test_no_dormant_service_was_started_without_updating_the_record(self):
        """The other direction. Starting one of these has consequences the record
        names — cloud_gateway's queue, tactical_engine's missing command sink — and
        they should be read before, not discovered after."""
        newly = sorted(STARTED & set(EXPECTED_DORMANT))
        assert not newly, (
            "These are recorded as dormant but main.py now starts them. Read the reason "
            "in EXPECTED_DORMANT, then move them to EXPECTED_STARTED:\n  "
            + "\n  ".join(newly)
        )

    def test_the_started_list_is_accurate(self):
        assert STARTED == EXPECTED_STARTED, (
            f"started set drifted.\n  now started: {sorted(STARTED)}\n"
            f"  recorded:    {sorted(EXPECTED_STARTED)}"
        )

    def test_every_dormant_service_has_a_stated_reason(self):
        """A name on a list explains nothing. The reason is what makes the next person
        able to decide whether starting it is safe."""
        for name in DORMANT:
            reason = EXPECTED_DORMANT.get(name, "")
            assert len(reason) > 40, f"{name} is recorded as dormant with no real reason"


class TestTheCloudGatewayOrdering:
    """The one dormant service whose absence actively destroys data if a producer is
    started without it."""

    def test_producers_are_not_started_while_the_gateway_is_dormant(self):
        if "cloud_gateway" in STARTED:
            pytest.skip("cloud_gateway is running; producers are free to start")
        live = sorted(CLOUD_GATEWAY_PRODUCERS & STARTED)
        assert not live, (
            f"{live} queue into cloud_gateway, which is dormant — its _flush_loop is "
            f"never launched, so events accumulate in a 10,000-entry in-memory list "
            f"that sheds the oldest and are silently lost. Start cloud_gateway first, "
            f"or give these a different sink."
        )

    def test_the_producer_list_is_still_accurate(self):
        """Guards the guard: if a producer is renamed, the ordering check above passes
        while protecting nothing."""
        import re

        source = "\n".join(
            (APP / "services" / f"{n}.py").read_text()
            for n in ("tactical_engine", "strategic_engine", "mlops_pipeline")
            if (APP / "services" / f"{n}.py").exists()
        )
        assert re.search(r"cloud_gateway\.\s*queue_", source), (
            "no cloud_gateway.queue_* call found in the modules recorded as producers; "
            "the ordering check is guarding a relationship that no longer exists"
        )
