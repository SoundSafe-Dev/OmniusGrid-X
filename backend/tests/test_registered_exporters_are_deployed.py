"""The exporter register is a claim about deployments; nothing checked it (FS-775).

`test_every_alert_watches_a_series_something_exports` splits alert metrics into two
populations: those this repository's Python exports, verified by AST, and those a
third-party exporter provides. The second population is an allowlist —

    INFRA_EXPORTERS = {
        "node_": "node-exporter (infra/prometheus + k8s monitoring stack)",
        "pg_":   "postgres exporter",
        ...
    }

— and the file is candid that this "is the honest boundary of the check". The boundary
was in the right place. The problem is that **nothing verified the claims inside it**,
and two of them were false:

  * `node_` said node-exporter was deployed to "infra/prometheus + k8s monitoring
    stack". There was no node-exporter in docker-compose.yml and none in
    infrastructure/k8s. `DiskSpaceCritical` (CRITICAL) and `HighMemoryUsage` (HIGH)
    both read `node_*`.
  * `pg_` said "postgres exporter". There was none, in either environment.

So the register was doing the opposite of its job: a metric got waved through
*because* it was named as an infra exporter's, and being named there was exactly the
thing nobody could check. Adding a prefix to that dict silenced the sweep.

This file closes it: every prefix must name a scrape job that exists in at least one
Prometheus configuration, and — for the exporters this repository deploys — a workload
in a manifest or a compose service. A prefix that cannot be traced to a deployment is
a wish, and the alerts resting on it are inert.

WHAT IT DELIBERATELY DOES NOT CHECK. Series produced by Prometheus itself
(`up`, `scrape_`, `prometheus_`), by the kubelet (`container_`, `kubelet_`) and by
operators the cluster installs rather than this repository (`cnpg_`, `keda_`) have no
manifest here to point at. Those are declared below with the reason, which keeps the
unverifiable set small, explicit, and reviewable — instead of the whole register being
unverifiable and looking identical to a checked one.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from tests.test_every_alert_watches_a_series_something_exports import INFRA_EXPORTERS

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
COMPOSE = REPO / "docker-compose.yml"
PROM_CONFIGS = [
    REPO / "infra" / "prometheus" / "prometheus.yml",
    REPO / "infrastructure" / "k8s" / "monitoring" / "prometheus-config.yml",
]
K8S = REPO / "infrastructure" / "k8s"

#: prefix -> the scrape job expected to carry it.
EXPECTED_JOB = {
    "node_": "node-exporter",
    "pg_": "postgres-exporter",
    "kube_": "kube-state-metrics",
    "redpanda_": "redpanda",
    "probe_": "blackbox-http",
    "http_requests_": "opsgrid-backend",
    "http_request_duration_": "opsgrid-backend",
    "prometheus_": "prometheus",
}

#: prefix -> why no scrape job or workload in this repository can be pointed at.
#: Each entry is a statement that the series arrives from outside anything we deploy.
NOT_OURS_TO_DEPLOY = {
    "up": "synthesised by Prometheus per target; exists wherever a target does",
    "scrape_": "synthesised by Prometheus per scrape",
    "process_": "prometheus_client's default collector, present in every Python target",
    "go_": "Go runtime collector, present in every Go-based exporter we scrape",
    "container_": "cAdvisor, embedded in the kubelet — not a workload we deploy",
    "kubelet_": "the kubelet's own volume stats — not a workload we deploy",
    "cnpg_": "installed by the CloudNativePG operator, not by this repository",
    "keda_": "installed by the KEDA operator, not by this repository",
}

#: prefix -> (compose service, k8s workload name). Exporters this repository ships.
EXPECTED_DEPLOYMENT = {
    "node_": ("node-exporter", "node-exporter"),
    "pg_": ("postgres-exporter", "postgres-exporter"),
    "probe_": ("blackbox-exporter", "blackbox-exporter"),
    "kube_": (None, "kube-state-metrics"),
}


def _scrape_jobs() -> dict[str, set[str]]:
    """config path -> job names it defines."""
    jobs: dict[str, set[str]] = {}
    for path in PROM_CONFIGS:
        doc = yaml.safe_load(path.read_text())
        jobs[path.name] = {
            j.get("job_name") for j in doc.get("scrape_configs", []) if j.get("job_name")
        }
    return jobs


def _compose_services() -> set[str]:
    return set(yaml.safe_load(COMPOSE.read_text()).get("services", {}))


def _k8s_workload_names() -> set[str]:
    """Deployment/DaemonSet/StatefulSet names across every manifest under k8s/."""
    names: set[str] = set()
    for path in K8S.rglob("*.yaml"):
        try:
            docs = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError:
            continue  # kustomize overlays with patch syntax are not our question here
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") in {"Deployment", "DaemonSet", "StatefulSet"}:
                name = (doc.get("metadata") or {}).get("name")
                if name:
                    names.add(name)
    return names


class TestTheMeasurementIsReal:
    def test_it_parsed_both_prometheus_configs(self):
        jobs = _scrape_jobs()
        assert len(jobs) == 2, jobs
        for name, found in jobs.items():
            assert len(found) >= 4, f"{name} yielded only {len(found)} jobs: {found}"

    def test_it_found_the_workloads(self):
        workloads = _k8s_workload_names()
        assert len(workloads) >= 8, f"only {len(workloads)} k8s workloads parsed"
        assert "backend" in workloads

    def test_every_prefix_is_classified(self):
        """No prefix may be silently neither-checked-nor-excused — which is the state
        the whole register was in."""
        unclassified = sorted(
            p for p in INFRA_EXPORTERS
            if p not in EXPECTED_JOB and p not in NOT_OURS_TO_DEPLOY
        )
        assert not unclassified, (
            f"{unclassified} are registered as infra-exporter metrics but this file "
            f"neither maps them to a scrape job nor records why they cannot be traced. "
            f"Adding a prefix to INFRA_EXPORTERS silences the alert sweep; it must not "
            f"also silence this one."
        )


@pytest.mark.parametrize("prefix", sorted(EXPECTED_JOB))
def test_every_registered_exporter_has_a_scrape_job(prefix):
    job = EXPECTED_JOB[prefix]
    jobs = _scrape_jobs()
    carrying = [config for config, found in jobs.items() if job in found]
    assert carrying, (
        f"INFRA_EXPORTERS claims `{prefix}*` comes from {INFRA_EXPORTERS[prefix]!r}, "
        f"but no Prometheus configuration defines a scrape job named {job!r}.\n\n"
        f"Jobs found: { {k: sorted(v) for k, v in jobs.items()} }\n\n"
        f"A metric family with no scrape job produces no series, so every alert over "
        f"`{prefix}*` is inert while looking perfectly healthy. This is how "
        f"DiskSpaceCritical (CRITICAL) and TimescaleDBDown (CRITICAL) spent their "
        f"entire lives."
    )


@pytest.mark.parametrize("prefix", sorted(EXPECTED_DEPLOYMENT))
def test_exporters_this_repo_ships_are_actually_deployed(prefix):
    compose_service, workload = EXPECTED_DEPLOYMENT[prefix]
    if compose_service is not None:
        assert compose_service in _compose_services(), (
            f"`{prefix}*` is registered as coming from {compose_service!r}, which is "
            f"not a service in docker-compose.yml. Local runs will have the alerts and "
            f"none of the series."
        )
    assert workload in _k8s_workload_names(), (
        f"`{prefix}*` is registered as coming from {workload!r}, and no Deployment, "
        f"DaemonSet or StatefulSet by that name exists under infrastructure/k8s/. "
        f"The alerts resting on `{prefix}*` cannot fire in the cluster — which is the "
        f"only environment where it matters."
    )


def test_the_probe_job_carries_the_target_the_sli_reads():
    """The SLI reads `probe_success{job="blackbox-http", probe_target="backend_ready"}`.
    A probe job that exists but never produces that label pair leaves availability
    uncomputable, and ProbeSignalMissing pages forever — the mirror-image failure of
    the one this sprint fixed, and just as bad."""
    for path in PROM_CONFIGS:
        doc = yaml.safe_load(path.read_text())
        job = next(
            (j for j in doc["scrape_configs"] if j.get("job_name") == "blackbox-http"),
            None,
        )
        assert job is not None, f"{path.name} defines no blackbox-http job"
        targets = [
            static.get("labels", {}).get("probe_target")
            for static in job.get("static_configs", [])
        ]
        assert "backend_ready" in targets, (
            f"{path.name}'s blackbox-http job probes {targets}, and the availability "
            f"SLI in slo_rules.yml reads probe_target=\"backend_ready\". Without it "
            f"the SLI is permanently absent."
        )
