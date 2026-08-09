"""The compose observability stack starts, scrapes once, and scrapes something (FS-516..519).

Four defects in the local stack, none of which any gate could see, because every gate checked
a *file* and none checked whether a process would come up and find anything.

**FS-516 — Prometheus could not start.** `docker-compose.yml` passed
`--alertmanager.url=http://alertmanager:9093`. That flag was **removed in Prometheus 2.0**, and
an unknown flag is fatal at startup. So the container exited immediately on every `docker
compose up`, and nobody running the stack locally has ever had metrics, alerts or SLO rules.
Four CI gates assert those rule files are well-formed; none of them had ever been loaded by a
running Prometheus. It was redundant too — `prometheus.yml:8-12` configures the alertmanager
the current way.

**FS-517 — one container, two jobs, every series doubled.** `prometheus.yml` defined
`edge-agent` at `edge-agent:9108` and `opsgrid-edge-agent` at `edge-agent-sim:9108`.
`edge-agent` is a network **alias** for `edge-agent-sim`, so both scraped the same container.
No alert rule or dashboard panel filters by `job`, so `sum(edge_agent_up)` counted every agent
twice and `EdgeAgentBufferHigh` would have fired two identical alerts each. **The fleet size
was wrong in the direction that looks like growth.**

**FS-518 — the simulator simulated nothing.** `edge-agent-sim` set no `COLLECTORS` and no
`COLLECTORS_FILE`, so the agent logged `no_collectors_configured` and produced no telemetry —
while the scrape job pointed at it reported it up and healthy.

**FS-519 — the metrics port matched nothing.** `main.py` defaulted `METRICS_PORT` to 9100. The
StatefulSet declares containerPort 9108, the compose service publishes 9108, and every scrape
target is 9108. Any deployment that did not set it explicitly served a full registry on a port
nothing scraped — and 9100 is the node_exporter port, so on a host running one the agent would
either be scraped as the node exporter or fail to bind.

WHAT TIES THEM TOGETHER, and why they are one file. Each is invisible to the validator that
owns its artefact: `promtool check config` does not know which flags the binary accepts,
`docker compose config` does not know an agent needs collectors, and neither knows which port
the other one uses. **The gap is not in any artefact — it is between them**, which is rule 122
in a different tree.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = REPO / "docker-compose.yml"
PROM = REPO / "infra" / "prometheus" / "prometheus.yml"
AGENT_MAIN = REPO / "edge-agent" / "opsgrid_agent" / "main.py"
STATEFULSET = REPO / "infrastructure" / "k8s" / "base" / "edge-agent-statefulset.yaml"

#: Flags Prometheus removed. Passing one is fatal at startup, not a warning.
#: Sourced from the 2.0 and 3.0 migration notes; each is here because it once shipped.
REMOVED_PROMETHEUS_FLAGS = {
    "--alertmanager.url": "removed in Prometheus 2.0 — configure `alerting.alertmanagers` in "
                          "prometheus.yml instead",
    "--alertmanager.notification-queue-capacity": "removed in Prometheus 2.0",
    "--storage.local.path": "removed in Prometheus 2.0 — use --storage.tsdb.path",
    "--storage.local.retention": "removed in Prometheus 2.0 — use --storage.tsdb.retention.time",
    "--web.telemetry-path": "removed in Prometheus 2.0",
    "--storage.tsdb.retention": "removed in Prometheus 3.0 — use --storage.tsdb.retention.time",
    "--rules.alert.for-outage-tolerance": "renamed in Prometheus 3.0",
}


def _compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text())


def _prom() -> dict:
    return yaml.safe_load(PROM.read_text())


def _service_names_and_aliases(compose: dict) -> set[str]:
    """Every name a container answers to on the compose network."""
    names: set[str] = set()
    for name, service in (compose.get("services") or {}).items():
        names.add(name)
        networks = service.get("networks")
        if isinstance(networks, dict):
            for spec in networks.values():
                if isinstance(spec, dict):
                    names.update(spec.get("aliases") or [])
    return names


class TestPrometheusCanStart:
    def test_no_removed_flag_is_passed(self):
        """FS-516. An unknown flag is fatal, so this is the difference between a stack that
        runs and one that has never run."""
        prometheus = (_compose()["services"] or {}).get("prometheus")
        assert prometheus, "no `prometheus` service in docker-compose.yml"
        command = prometheus.get("command") or []
        offenders = [
            f"{flag} ({reason})"
            for flag, reason in REMOVED_PROMETHEUS_FLAGS.items()
            if any(str(arg).startswith(flag) for arg in command)
        ]
        assert not offenders, (
            f"the compose Prometheus is passed flags the binary rejects: {offenders}. An "
            f"unknown flag is fatal at startup — the container exits immediately and the "
            f"whole local observability stack silently does not exist."
        )

    def test_the_alertmanager_is_still_configured_somewhere(self):
        """Removing the flag must not remove the routing. It was redundant, not absent —
        and a fix that made the container start while dropping alerting entirely would pass
        the test above and be worse."""
        alerting = _prom().get("alerting") or {}
        targets = [
            target
            for manager in alerting.get("alertmanagers") or []
            for static in manager.get("static_configs") or []
            for target in static.get("targets") or []
        ]
        assert targets, (
            "prometheus.yml configures no alertmanager. Every rule in alerts.yml would "
            "evaluate and fire into nothing."
        )


class TestEveryScrapeTargetIsRealAndScrapedOnce:
    def test_each_static_target_names_a_compose_service(self):
        compose = _compose()
        known = _service_names_and_aliases(compose)
        problems = []
        for job in _prom().get("scrape_configs") or []:
            for static in job.get("static_configs") or []:
                for target in static.get("targets") or []:
                    host = str(target).split(":")[0]
                    if host in {"localhost", "127.0.0.1"}:
                        continue
                    if host not in known:
                        problems.append(f"job {job['job_name']!r} -> {target!r}")
        assert not problems, (
            f"these scrape targets name no compose service or alias: {problems}. The job is "
            f"permanently DOWN, which on a dashboard is indistinguishable from a component "
            f"that is down."
        )

    def test_no_two_jobs_scrape_the_same_target(self):
        """FS-517. Two jobs on one container is not redundancy — it is double counting.

        Nothing in `alerts.yml` or the Grafana dashboards filters by `job`, so identical
        series under two job labels make `sum(edge_agent_up)` report twice the fleet and
        `EdgeAgentBufferHigh` fire twice per agent.
        """
        compose = _compose()
        # Resolve aliases to the service they belong to, so an alias and its service are
        # recognised as the same container — which is exactly how this hid.
        canonical: dict[str, str] = {}
        for name, service in (compose.get("services") or {}).items():
            canonical[name] = name
            networks = service.get("networks")
            if isinstance(networks, dict):
                for spec in networks.values():
                    if isinstance(spec, dict):
                        for alias in spec.get("aliases") or []:
                            canonical[alias] = name

        seen: dict[tuple[str, str], str] = {}
        collisions = []
        for job in _prom().get("scrape_configs") or []:
            for static in job.get("static_configs") or []:
                for target in static.get("targets") or []:
                    host, _, port = str(target).partition(":")
                    key = (canonical.get(host, host), port)
                    if key in seen:
                        collisions.append(
                            f"jobs {seen[key]!r} and {job['job_name']!r} both scrape "
                            f"{key[0]}:{key[1]}"
                        )
                    else:
                        seen[key] = job["job_name"]
        assert not collisions, (
            f"{collisions}. Every series is then exported twice under different `job` labels, "
            f"and no rule or panel filters by job — so counts double and alerts duplicate."
        )


class TestTheSimulatorProducesSomething:
    def test_it_configures_at_least_one_collector(self):
        """FS-518. An agent with no collectors logs `no_collectors_configured` and emits
        nothing, while its scrape target reports it up."""
        sim = (_compose()["services"] or {}).get("edge-agent-sim")
        assert sim, "no `edge-agent-sim` service in docker-compose.yml"
        env = sim.get("environment") or {}
        assert env.get("COLLECTORS") or env.get("COLLECTORS_FILE"), (
            "edge-agent-sim sets neither COLLECTORS nor COLLECTORS_FILE, so the service "
            "named 'simulator' produces no telemetry at all — the demo stack has a healthy "
            "agent and an empty database."
        )

    def test_its_collectors_declare_an_explicit_source(self):
        """FS-508's posture applies to the simulator too: a synthetic-capable collector with
        no `source` is refused under EDGE_REQUIRE_EXPLICIT_SOURCES, so a config that relies on
        the old permissive default would break the moment the demo stack adopts it."""
        import json

        sim = (_compose()["services"] or {})["edge-agent-sim"]
        raw = (sim.get("environment") or {}).get("COLLECTORS")
        if not raw:
            pytest.skip("configured via COLLECTORS_FILE; checked where that file lives")
        for entry in json.loads(raw):
            if entry.get("collector_type") in {"audio", "video"}:
                assert (entry.get("config") or {}).get("source"), (
                    f"{entry['collector_type']} collector {entry.get('asset_id')!r} declares "
                    f"no `source`, so it synthesizes silently under the old default and is "
                    f"refused under the new one (FS-508)"
                )


class TestTheMetricsPortAgreesEverywhere:
    def test_the_agent_default_matches_what_is_scraped(self):
        """FS-519. The default listened on a port nothing scraped, so an agent deployed
        without an explicit METRICS_PORT exported a full registry into the void."""
        default = re.search(r"METRICS_PORT',\s*'(\d+)'", AGENT_MAIN.read_text())
        assert default, "the METRICS_PORT default could not be read from main.py"
        default_port = default.group(1)

        scraped = {
            str(target).split(":")[-1]
            for job in _prom().get("scrape_configs") or []
            for static in job.get("static_configs") or []
            for target in static.get("targets") or []
            if "edge-agent" in str(target)
        }
        assert scraped, "no edge-agent scrape target found; this check has no subject"
        assert default_port in scraped, (
            f"the agent defaults METRICS_PORT to {default_port} and the scrape targets are "
            f"{sorted(scraped)}. A deployment that does not set it explicitly serves metrics "
            f"where nothing looks, so every edge alert stays silent for the honest reason "
            f"that no series exists. 9100 is also the node_exporter port."
        )

    def test_the_statefulset_container_port_matches(self):
        default = re.search(r"METRICS_PORT',\s*'(\d+)'", AGENT_MAIN.read_text()).group(1)
        doc = yaml.safe_load(STATEFULSET.read_text())
        ports = {
            str(port["containerPort"])
            for container in doc["spec"]["template"]["spec"]["containers"]
            for port in container.get("ports") or []
        }
        assert default in ports, (
            f"the agent defaults to port {default} and the StatefulSet declares {sorted(ports)}"
        )
