"""A metric that is always zero — or worse, always absent — is a lie an operator can query (FS-696).

THE BACKEND TWIN of the edge agent's guard by the same name, and the backend's instance was
worse. The edge sweep found one orphaned counter from a merge. This sweep found **eight**,
all defined beside the `/metrics` endpoint in `app/api/health.py` — the API process — while
the quantities they described (telemetry ingested, PackML transitions, ingestion lag, edge
buffer depth, OCR accuracy, active alerts) happen in the ingestion worker or on the edge
agent. Two were load-bearing: `IngestionLagHighApp` and `OcrAccuracyLow` alerted on series
only those dead definitions named, so **neither alert could ever fire**, and their promtool
tests passed by writing the series by hand (rule 188).

An unlabelled dead metric exports zeros — a flat line read as "no traffic". A LABELLED dead
metric is subtler: `generate_latest` emits only its HELP/TYPE header until a label
combination is touched, so the operator greps `/metrics`, finds the name documented, builds
the dashboard, and gets *no data* rather than a zero — indistinguishable from a label filter
typo, which is where the debugging time goes.

WHAT THIS DOES NOT CATCH — same caveat as the edge twin: a metric with ONE call site out of
many it should have passes here (`errors_total` did, for FS-691). Rule 194: the
zero-call-site sweep and the disproportion check are different questions.
"""

from __future__ import annotations

import ast
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parent.parent / "app"

#: Metrics deliberately defined without an emitter, with the reason. Empty, and the bar is
#: high: the eight that were here were deleted, not registered.
DELIBERATELY_UNFED: dict[str, str] = {}


def _sources() -> dict[pathlib.Path, str]:
    return {p: p.read_text() for p in APP.rglob("*.py")}


def _definitions(sources: dict[pathlib.Path, str]) -> dict[str, tuple[str, str]]:
    """Module-level names bound to a prometheus_client collector: var -> (file, kind)."""
    found: dict[str, tuple[str, str]] = {}
    for path, src in sources.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            func = node.value.func
            kind = getattr(func, "id", getattr(func, "attr", ""))
            if kind in {"Counter", "Gauge", "Histogram", "Summary"}:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = (str(path.relative_to(APP.parent)), kind)
    return found


def _unfed() -> list[str]:
    """Metrics never USED anywhere in `app/` beyond their own definition.

    AST `Name` loads, not a text search — and that distinction was proven necessary by
    this file's own mutation run: unwiring `INGESTION_LAG` from the worker while leaving
    its `from app.workers.health_server import INGESTION_LAG` line intact passed the
    text-based draft, because the import matched the regex. An import is a reference,
    not a feeding; only an attribute access (`.inc()`, `.set()`, `.labels()`) or other
    load outside the defining assignment counts here.
    """
    sources = _sources()
    uses: dict[str, int] = {}
    for _path, src in sources.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                uses[node.id] = uses.get(node.id, 0) + 1
    return sorted(
        f"{var} ({kind}) in {home}"
        for var, (home, kind) in _definitions(sources).items()
        if uses.get(var, 0) == 0
    )


class TestTheMeasurementIsReal:
    """Rule 165 — assert the denominator before believing an empty result."""

    def test_it_found_the_metrics(self):
        defs = _definitions(_sources())
        assert len(defs) >= 30, f"only {len(defs)} metrics found — the parse is not working"
        assert "INGESTION_LAG" in defs and "edge_agent_last_heartbeat" in defs

    def test_a_fed_metric_is_seen_as_fed(self):
        """NEGATIVE CONTROL. INGESTION_LAG is fed by the ingestion worker — the wiring
        FS-696 added is precisely what moves it off the dead list, and a detector that
        still reported it would report every metric in the tree."""
        assert not any(item.startswith("INGESTION_LAG ") for item in _unfed())

    def test_the_deleted_eight_stayed_deleted(self):
        """The eight dead definitions were removed from health.py, not wired — there is
        nothing in the API process for them to measure. This pins the deletion, because
        the path of least resistance for a revert-happy merge is to bring them back."""
        health = (APP / "api" / "health.py").read_text()
        for name in ("TELEMETRY_INGESTED", "ACTIVE_ASSETS", "PACKML_STATE_CHANGES",
                     "EDGE_BUFFER_MESSAGES", "OCR_ACCURACY", "ALERTS_ACTIVE"):
            assert f"{name} = " not in health, (
                f"{name} is back in health.py — it was deleted (FS-696) because the API "
                f"process cannot feed it; define it in the process that can"
            )


def test_every_metric_is_fed_by_something():
    unfed = [m for m in _unfed() if m.split(" ")[0] not in DELIBERATELY_UNFED]
    assert not unfed, (
        f"{unfed} are defined and incremented by nothing in app/.\n\n"
        f"A dead unlabelled metric exports zeros; a dead labelled one exports only its "
        f"HELP text, and an alert written against either can never fire — which is how "
        f"IngestionLagHighApp and OcrAccuracyLow spent their whole lives unable to page "
        f"anyone (FS-696). Wire it in the process that produces the quantity, or delete it."
    )
