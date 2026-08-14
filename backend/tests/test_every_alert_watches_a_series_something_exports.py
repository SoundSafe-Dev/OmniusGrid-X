"""An alert over a series nothing exports can never fire, and looks exactly like coverage (FS-695/696).

THE CLASS, FOUND THREE TIMES BY HAND before this guard existed:
  * `EdgeAgentOffline` (HIGH) watched `edge_agent_up == 0`, and nothing writes 0 — the
    gauge is set only when a heartbeat arrives (FS-695).
  * `IngestionLagHighApp` watched `opsgrid_ingestion_lag_seconds`, defined in the API
    process where no ingestion happens and fed by nothing (FS-696).
  * `OcrAccuracyLow` watched `opsgrid_ocr_accuracy`, same story (FS-696).
All three had passing promtool tests, because a promtool test writes its input series by
hand — it proves the rule fires GIVEN the series, not that the series exists. Rule 188.
This file closes the half promtool cannot ask: every metric name an alert expression
references must be exported by this repository's code or by a deployed exporter we name.

WHAT COUNTS AS EXPORTED. Series names are collected by AST from both codebases (`app/`
and `edge-agent/opsgrid_agent/`), with prometheus_client's suffix behaviour applied:
a Counter named `foo` is exported as `foo_total`, a Histogram grows `_bucket`/`_sum`/
`_count`. Infra exporters (node_exporter, kube-state-metrics, cAdvisor, CloudNativePG,
Redpanda, Prometheus itself) cannot be verified from this repo; they are a named register
with the deployment that provides each, which is the honest boundary of the check.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
ALERTS = REPO / "infra" / "prometheus" / "alerts.yml"
CODE_ROOTS = [REPO / "backend" / "app", REPO / "edge-agent" / "opsgrid_agent"]

#: Metric families served by deployed exporters, not by code in this repository. Each
#: entry is a claim that the named deployment exports that family — auditable against
#: the manifests, not against Python.
INFRA_EXPORTERS = {
    "node_": "node-exporter (infra/prometheus + k8s monitoring stack)",
    "kube_": "kube-state-metrics (infrastructure/k8s/monitoring)",
    "container_": "cAdvisor via kubelet",
    "cnpg_": "CloudNativePG operator (infrastructure/k8s/database-ha)",
    "redpanda_": "Redpanda's own admin metrics endpoint (scrape job 'redpanda')",
    "pg_": "postgres exporter",
    "up": "Prometheus scrape health, synthesized per target",
    "process_": "prometheus_client default process collector",
    "go_": "Go runtime metrics from Go-based exporters",
    "prometheus_": "Prometheus self-monitoring",
    "http_requests_": "prometheus-fastapi-instrumentator / middleware family",
    "scrape_": "Prometheus per-scrape synthetics",
}

#: PromQL syntax that the identifier regex also matches. Functions and keywords, not
#: series. Extending this list is fine; putting a metric name here is not.
PROMQL_NOISE = {
    "rate", "irate", "increase", "sum", "count", "avg", "min", "max", "abs", "time",
    "by", "on", "ignoring", "unless", "and", "or", "without", "offset", "bool",
    "histogram_quantile", "label_replace", "absent", "absent_over_time", "changes",
    "delta", "idelta", "predict_linear", "clamp_min", "clamp_max", "round", "vector",
    "avg_over_time", "max_over_time", "min_over_time", "sum_over_time", "topk", "bottomk",
}


def _exported_series() -> set[str]:
    found: set[str] = set()
    for root in CODE_ROOTS:
        for path in root.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                kind = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if kind not in {"Counter", "Gauge", "Histogram", "Summary"} or not node.args:
                    continue
                first = node.args[0]
                if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                    continue
                name = first.value
                found.add(name)
                if kind == "Counter":
                    found.add(name if name.endswith("_total") else f"{name}_total")
                if kind == "Histogram":
                    found.update({f"{name}_bucket", f"{name}_sum", f"{name}_count"})
                if kind == "Summary":
                    found.update({f"{name}_sum", f"{name}_count"})
    return found


def _label_names(expr: str) -> set[str]:
    """Identifiers that are labels, not series: inside {...} matchers before an operator,
    and inside by/on/without/ignoring (...) clauses."""
    labels: set[str] = set()
    for body in re.findall(r"\{([^}]*)\}", expr):
        labels |= set(re.findall(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:=~|!~|!=|=)", body))
    for body in re.findall(r"\b(?:by|on|without|ignoring)\s*\(([^)]*)\)", expr):
        labels |= set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", body))
    return labels


def _referenced_metrics() -> dict[str, list[str]]:
    """metric name -> alert names referencing it, from every expr in alerts.yml."""
    text = ALERTS.read_text()
    refs: dict[str, list[str]] = {}
    current_alert = "?"
    for line in text.splitlines():
        alert_match = re.search(r"-\s*alert:\s*(\w+)", line)
        if alert_match:
            current_alert = alert_match.group(1)
        expr_match = re.search(r"expr:\s*(.+)", line)
        if not expr_match:
            continue
        expr = expr_match.group(1)
        labels = _label_names(expr)
        stripped = re.sub(r'"[^"]*"', "", expr)  # label values and annotations
        for ident in set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", stripped)):
            if ident in PROMQL_NOISE or ident in labels:
                continue
            refs.setdefault(ident, []).append(current_alert)
    return refs


def _unbacked() -> dict[str, list[str]]:
    exported = _exported_series()
    return {
        name: alerts
        for name, alerts in _referenced_metrics().items()
        if name not in exported
        and not any(name.startswith(prefix) or name == prefix.rstrip("_")
                    for prefix in INFRA_EXPORTERS)
    }


class TestTheMeasurementIsReal:
    def test_it_found_the_exported_series(self):
        exported = _exported_series()
        assert len(exported) >= 60, f"only {len(exported)} exported series found"
        assert "edge_collector_errors_total" in exported
        assert "opsgrid_ingestion_lag_seconds" in exported, (
            "the worker's lag gauge is gone — IngestionLagHighApp is unbacked again"
        )

    def test_it_read_the_alert_expressions(self):
        refs = _referenced_metrics()
        assert len(refs) >= 25, f"only {len(refs)} metric references parsed from alerts.yml"
        assert "edge_agent_last_heartbeat_timestamp_seconds" in refs

    def test_it_would_catch_the_fs695_shape(self):
        """POSITIVE CONTROL: a metric name nothing exports must come back unbacked. This
        is the exact question EdgeAgentOffline failed for months."""
        exported = _exported_series()
        assert "opsgrid_metric_that_never_existed" not in exported

    def test_labels_are_not_mistaken_for_series(self):
        """NEGATIVE CONTROL: `agent_id` appears in nearly every expr as a label; a parser
        that reports it as an unbacked series would bury the real findings in noise —
        which is precisely what the first draft of this sweep did."""
        assert "agent_id" in _label_names('edge_agent_up{agent_id="x"} == 0')
        assert "topic" in _label_names("max by (topic) (opsgrid_ingestion_lag_seconds)")

    @pytest.mark.parametrize("prefix", sorted(INFRA_EXPORTERS))
    def test_every_infra_register_entry_names_its_provider(self, prefix):
        assert INFRA_EXPORTERS[prefix].strip(), f"{prefix} is registered with no provider"


def test_every_alert_watches_a_series_something_exports():
    unbacked = {k: sorted(set(v)) for k, v in sorted(_unbacked().items())}
    assert not unbacked, (
        f"These alert expressions reference series that no code in this repository "
        f"exports and no registered infra exporter provides:\n{unbacked}\n\n"
        f"An alert over a series that never exists can never fire — and its promtool "
        f"test still passes, because promtool tests hand-write their input series. "
        f"EdgeAgentOffline (HIGH) was in this state for its whole life. Either export "
        f"the metric from the process that produces the quantity, fix the expression, "
        f"or register the exporter that provides it with its deployment."
    )
