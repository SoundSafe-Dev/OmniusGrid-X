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
    "http_request_duration_": "request-context middleware latency histogram family",
    "scrape_": "Prometheus per-scrape synthetics",
    "keda_": "KEDA operator metrics (infrastructure/k8s/autoscaling)",
    # FS-769. The availability SLI's primary input. Deployed as `blackbox-exporter` in
    # docker-compose.yml and infrastructure/k8s/monitoring/blackbox-exporter.yaml, and
    # scraped by the `blackbox-http` job in both Prometheus configs. It runs in a
    # separate process from the backend on purpose: that is the only reason
    # `probe_success` still reports — reporting 0 — when the backend is gone.
    "probe_": "blackbox-exporter (scrape job 'blackbox-http', compose + k8s monitoring)",
    # Per-volume usage, published by the kubelet alongside cAdvisor. Paired with
    # kube-state-metrics' requested-size series to give PVC fullness.
    "kubelet_": "kubelet volume stats (scraped with cAdvisor via the kubelet)",
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


def _rules() -> list[tuple[str, str]]:
    r"""(rule name, full expression) for every rule in alerts.yml.

    PARSED AS YAML, NOT LINE-SCANNED (FS-774). The previous implementation matched
    `expr:\s*(.+)` per line, so an expression written as a YAML block scalar —

        expr: |
          sum(rate(opsgrid_http_requests_total{status=~"5.."}[5m]))
            / sum(rate(opsgrid_http_requests_total[5m])) > 0.05

    — was captured as the literal string "|" and its metric names were never examined.
    THIRTEEN OF FIFTY-THREE expressions, a quarter of the file, were invisible to the
    sweep whose entire purpose is to notice alerts over series nothing exports. Two
    real defects had been sitting in that blind spot since the rules were written:

      * `AssetOffline` watches `opsgrid_asset_last_seen_timestamp_seconds`, which
        nothing in either codebase exports — the asset-offline alert, on an IIoT
        platform, could never fire.
      * `SlowDatabaseQueries` watches `postgresql_stat_activity_max_tx_duration`. There
        is no postgres_exporter deployed, and the name is not even the one it would
        export if there were (`pg_stat_activity_max_tx_duration`), so the rule would
        stay inert through the very deployment that was supposed to fix it.

    This is rule 165 turned on the sweep itself: it was passing over a quarter of its
    population, and a sweep that silently narrows reads exactly like a clean one.
    """
    import yaml

    doc = yaml.safe_load(ALERTS.read_text())
    found: list[tuple[str, str]] = []
    for group in doc.get("groups", []):
        for rule in group.get("rules", []):
            name = rule.get("alert") or rule.get("record") or "?"
            expr = rule.get("expr")
            if isinstance(expr, str):
                found.append((name, expr))
    return found


def _referenced_metrics() -> dict[str, list[str]]:
    """metric name -> alert names referencing it, from every expr in alerts.yml."""
    refs: dict[str, list[str]] = {}
    for name, expr in _rules():
        labels = _label_names(expr)
        stripped = re.sub(r'"[^"]*"', "", expr)  # label values and annotations
        for ident in set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", stripped)):
            if ident in PROMQL_NOISE or ident in labels:
                continue
            refs.setdefault(ident, []).append(name)
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

    def test_it_reads_multi_line_expressions(self):
        """THE BLIND SPOT, pinned (FS-774). A quarter of this file's expressions are YAML
        block scalars, and the line-scanning predecessor captured them as the string
        "|" — so the sweep reported a clean population while never looking at thirteen
        rules, two of which were broken. A regression here is silent by construction:
        the sweep keeps passing, over less."""
        multi = [(n, e) for n, e in _rules() if "\n" in e.strip()]
        assert len(multi) >= 10, (
            f"only {len(multi)} multi-line expressions parsed — expected ~13. The YAML "
            f"parse has regressed to line-scanning and the sweep is quietly narrower."
        )
        # A metric that appears ONLY inside a block scalar must be reachable.
        refs = _referenced_metrics()
        assert "opsgrid_notification_delivery_failures_total" in refs or any(
            "opsgrid_" in e for _n, e in multi
        ), "no block-scalar metric name reached _referenced_metrics()"

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


def _recorded_series() -> set[str]:
    """Recording-rule outputs from slo_rules.yml — legitimate series Prometheus itself
    materializes, which dashboards may query."""
    slo = REPO / "infra" / "prometheus" / "slo_rules.yml"
    if not slo.exists():
        return set()
    return set(re.findall(r"record:\s*(\S+)", slo.read_text()))


def _dashboard_exprs() -> list[tuple[str, str, str]]:
    """(dashboard file, panel title, expr) for every panel target, via json — the regex
    draft of this sweep reported `horizontalpodautoscaler` and `cronjob` as unbacked
    series because escaped quotes inside the raw JSON defeated its label parser. Parsed
    JSON has no escaping problem."""
    import json

    found = []
    dash_dir = REPO / "infra" / "grafana" / "provisioning" / "dashboards"
    for path in sorted(dash_dir.glob("*.json")):
        data = json.loads(path.read_text())
        for panel in data.get("panels", []):
            for target in panel.get("targets", []):
                expr = target.get("expr")
                if expr:
                    found.append((path.name, panel.get("title", "?"), expr))
    return found


def test_every_dashboard_panel_queries_a_series_something_exports():
    """The dashboard half of the same question (FS-701). backend-system.json shipped with
    FIVE panels querying metrics that were never fed — 'Telemetry ingested / sec',
    'Ingest latency p95', 'PackML state changes / sec', 'Active assets', 'Active alerts'
    all read the dead health.py definitions FS-696 deleted, and had therefore displayed
    "No data" since the dashboard was created. A dashboard of empty panels reads as "the
    system is idle", not as "these queries are wrong"."""
    exported = _exported_series()
    recorded = _recorded_series()
    unbacked: dict[str, list[str]] = {}
    for dashboard, title, expr in _dashboard_exprs():
        labels = _label_names(expr)
        stripped = re.sub(r'"[^"]*"', "", expr)
        for ident in set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_:]{3,}", stripped)):
            if ident in PROMQL_NOISE or ident in labels or ident in recorded:
                continue
            if ident in exported:
                continue
            if any(ident.startswith(p) or ident == p.rstrip("_") for p in INFRA_EXPORTERS):
                continue
            unbacked.setdefault(ident, []).append(f"{dashboard}: {title}")
    assert not unbacked, (
        f"Dashboard panels query series nothing exports:\n{unbacked}\n\n"
        f"A panel over a series that never exists renders 'No data' forever and reads "
        f"as an idle system. Point it at a real series or delete the panel."
    )


def test_the_dashboard_sweep_reads_the_dashboards():
    """Rule 165 for the sweep above — five dashboards, at least twenty panel targets."""
    exprs = _dashboard_exprs()
    assert len(exprs) >= 20, f"only {len(exprs)} panel expressions found"
    assert any("opsgrid_ingestion_lag_seconds" in e for _f, _t, e in exprs)


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
