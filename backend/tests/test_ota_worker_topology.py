from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from app.workers import ota_rollouts as worker_module


REPO_ROOT = Path(__file__).resolve().parents[2]


class RecordingService:
    def __init__(self, name, events, *, fail_start=False):
        self.name = name
        self.events = events
        self.fail_start = fail_start

    async def start(self):
        self.events.append(f"{self.name}:start")
        if self.fail_start:
            raise RuntimeError(f"{self.name} failed")

    async def stop(self):
        self.events.append(f"{self.name}:stop")


@pytest.mark.asyncio
async def test_worker_starts_publisher_first_and_stops_in_reverse_order():
    events = []
    command_service = RecordingService("command", events)
    rollout_service = RecordingService("rollout", events)
    stop_event = asyncio.Event()
    stop_event.set()

    await worker_module.run(
        stop_event=stop_event,
        command_service=command_service,
        rollout_service=rollout_service,
    )

    assert events == [
        "command:start",
        "rollout:start",
        "rollout:stop",
        "command:stop",
    ]


@pytest.mark.asyncio
async def test_worker_cleans_up_when_rollout_start_fails():
    events = []
    command_service = RecordingService("command", events)
    rollout_service = RecordingService("rollout", events, fail_start=True)

    with pytest.raises(RuntimeError, match="rollout failed"):
        await worker_module.run(
            command_service=command_service,
            rollout_service=rollout_service,
        )

    assert events == [
        "command:start",
        "rollout:start",
        "rollout:stop",
        "command:stop",
    ]


@pytest.mark.asyncio
async def test_worker_cleans_up_when_command_start_fails():
    events = []
    command_service = RecordingService("command", events, fail_start=True)
    rollout_service = RecordingService("rollout", events)

    with pytest.raises(RuntimeError, match="command failed"):
        await worker_module.run(
            command_service=command_service,
            rollout_service=rollout_service,
        )

    assert events == ["command:start", "command:stop"]


def _mock_main_lifecycle(monkeypatch, main_module):
    monkeypatch.setattr(main_module, "init_db", AsyncMock())
    for service, methods in (
        (main_module.websocket_manager, ("connect", "disconnect")),
        (main_module.command_executor, ("start", "stop")),
        (main_module.oee_calculator, ("start", "stop")),
        (main_module.export_scheduler, ("start", "stop")),
        (main_module.compliance_report_dispatcher, ("start", "stop")),
        (main_module.rollout_orchestrator, ("start", "stop")),
        (main_module.report_scheduler, ("start", "stop")),
        (main_module.error_tracker, ("start", "stop")),
        (main_module.export_processor, ("close",)),
    ):
        for method in methods:
            monkeypatch.setattr(service, method, AsyncMock())


@pytest.mark.asyncio
async def test_api_lifespan_skips_ota_services_in_worker_mode(monkeypatch):
    import app.main as main_module

    _mock_main_lifecycle(monkeypatch, main_module)
    monkeypatch.setattr(main_module.settings, "SCHEDULERS_IN_API", False)

    async with main_module.lifespan(main_module.app):
        pass

    main_module.command_executor.start.assert_not_awaited()
    main_module.command_executor.stop.assert_not_awaited()
    main_module.rollout_orchestrator.start.assert_not_awaited()
    main_module.rollout_orchestrator.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_lifespan_keeps_explicit_single_process_mode(monkeypatch):
    import app.main as main_module

    _mock_main_lifecycle(monkeypatch, main_module)
    monkeypatch.setattr(main_module.settings, "SCHEDULERS_IN_API", True)

    async with main_module.lifespan(main_module.app):
        pass

    main_module.command_executor.start.assert_awaited_once()
    main_module.rollout_orchestrator.start.assert_awaited_once()
    main_module.rollout_orchestrator.stop.assert_awaited_once()
    main_module.command_executor.stop.assert_awaited_once()


def _environment_map(container):
    environment = container["env"]
    return {item["name"]: item.get("value") for item in environment}


def _secret_reference(container, name):
    environment = {item["name"]: item for item in container["env"]}
    return environment[name]["valueFrom"]["secretKeyRef"]


def test_compose_and_k8s_use_one_dedicated_ota_owner():
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    compose_backend = compose["services"]["backend"]
    compose_worker = compose["services"]["ota-rollout-worker"]

    def _effective(value: str) -> str:
        # Converged compose uses the env-overridable form
        # "${SCHEDULERS_IN_API:-false}" — same default, still operator-tunable.
        # Normalize "${VAR:-default}" to its default before asserting.
        value = str(value)
        if value.startswith("${") and ":-" in value and value.endswith("}"):
            return value[value.index(":-") + 2 : -1]
        return value

    assert _effective(compose_backend["environment"]["SCHEDULERS_IN_API"]) == "false"
    assert _effective(compose_worker["environment"]["SCHEDULERS_IN_API"]) == "false"
    assert compose_worker["command"] == "python -m app.workers.ota_rollouts"
    assert compose_worker["depends_on"] == {
        # migrate gate: the one-shot schema builder must finish before any
        # DB-writing worker starts (the initdb-mount removal fix).
        "migrate": {"condition": "service_completed_successfully"},
        "timescaledb": {"condition": "service_healthy"},
        "redpanda": {"condition": "service_healthy"},
    }

    required_worker_env = {
        "DATABASE_URL",
        "REDPANDA_URL",
        "REDPANDA_COMMAND_TOPIC",
        "REDPANDA_COMMAND_ACK_TOPIC",
        "REDPANDA_COMMAND_DLQ_TOPIC",
        "SIGNED_URL_SECRET_KEY",
        "SIGNED_URL_ALGORITHM",
        "SIGNED_URL_ISSUER",
        "SIGNED_URL_AUDIENCE",
        "EXPORT_PUBLIC_BASE_URL",
        "OTA_ROLLOUT_DISPATCH_ENABLED",
        "OTA_ROLLOUT_DISPATCH_INTERVAL_SECONDS",
        "OTA_ROLLOUT_DEFAULT_COMMAND_TIMEOUT_SECONDS",
        "OTA_ROLLOUT_DEFAULT_HEALTH_TIMEOUT_SECONDS",
        "OTA_ROLLOUT_DEFAULT_MIN_SUCCESS_RATIO",
    }
    assert required_worker_env <= set(compose_worker["environment"])

    kustomization = yaml.safe_load(
        (REPO_ROOT / "infrastructure/k8s/base/kustomization.yaml").read_text()
    )
    assert kustomization["resources"].count(
        "ota-rollout-worker-deployment.yaml"
    ) == 1

    k8s_base = REPO_ROOT / "infrastructure/k8s/base"
    backend_manifest = k8s_base / "backend-deployment.yaml"
    backend = yaml.safe_load(backend_manifest.read_text())
    worker = yaml.safe_load(
        (k8s_base / "ota-rollout-worker-deployment.yaml").read_text()
    )
    backend_container = backend["spec"]["template"]["spec"]["containers"][
        0
    ]
    backend_env = _environment_map(backend_container)
    worker_container = worker["spec"]["template"]["spec"]["containers"][0]
    worker_env = _environment_map(worker_container)

    assert backend_env["SCHEDULERS_IN_API"] == "false"
    assert worker["spec"]["replicas"] == 1
    assert worker_container["command"] == [
        "python",
        "-m",
        "app.workers.ota_rollouts",
    ]
    assert worker_env["SCHEDULERS_IN_API"] == "false"
    assert required_worker_env <= set(worker_env)
    assert worker_env["REDPANDA_COMMAND_TOPIC"] == "opsgrid.commands"
    assert worker_env["REDPANDA_COMMAND_ACK_TOPIC"] == "opsgrid.commands.acks"
    assert worker_env["REDPANDA_COMMAND_DLQ_TOPIC"] == "opsgrid.commands.dlq"
    signed_url_secret = {"name": "signed-url-secret", "key": "secret"}
    assert (
        _secret_reference(backend_container, "SIGNED_URL_SECRET_KEY")
        == signed_url_secret
    )
    assert (
        _secret_reference(worker_container, "SIGNED_URL_SECRET_KEY")
        == signed_url_secret
    )

    network_documents = yaml.safe_load_all(
        (k8s_base / "ingress.yaml").read_text()
    )
    policies = {
        document["metadata"]["name"]: document
        for document in network_documents
        if document["kind"] == "NetworkPolicy"
    }
    worker_egress = policies["allow-ota-rollout-worker-egress"]["spec"]
    assert worker_egress["podSelector"]["matchLabels"] == {
        "app.kubernetes.io/name": "ota-rollout-worker"
    }
    egress_ports = {
        port["port"]
        for rule in worker_egress["egress"]
        for port in rule["ports"]
    }
    assert {53, 5432, 9092} <= egress_ports


def _network_policies():
    k8s_base = REPO_ROOT / "infrastructure/k8s/base"
    network_documents = yaml.safe_load_all((k8s_base / "ingress.yaml").read_text())
    return {
        document["metadata"]["name"]: document
        for document in network_documents
        if document and document["kind"] == "NetworkPolicy"
    }


def _egress_ports(policy_spec):
    return {
        port["port"]
        for rule in policy_spec["egress"]
        for port in rule["ports"]
    }


def test_per_workload_egress_policies_exist_with_dns_and_datastores():
    """FS-116: every default-deny egress workload gets a scoped allow-list.

    Each of the four app workloads (the OTA worker is covered separately above)
    must have its own ``allow-<workload>-egress`` NetworkPolicy that selects the
    workload, is Egress-typed, and permits at minimum DNS (53), TimescaleDB
    (5432) and Redpanda (9092). This guards the default-deny egress FS-78 set:
    if a policy is dropped, an enforcing CNI would silently cut the workload off.
    """
    policies = _network_policies()

    # No lingering broad grant — FS-116 replaced allow-app-egress with the
    # per-workload policies below.
    assert "allow-app-egress" not in policies

    for workload in (
        "backend",
        "ingestion-worker",
        "export-worker",
        "compliance-reports-worker",
    ):
        name = f"allow-{workload}-egress"
        assert name in policies, f"missing egress policy {name}"
        spec = policies[name]["spec"]
        assert spec["podSelector"]["matchLabels"] == {
            "app.kubernetes.io/name": workload
        }
        assert spec["policyTypes"] == ["Egress"]
        assert {53, 5432, 9092} <= _egress_ports(spec)

    # backend additionally needs Redis and outbound HTTPS/443.
    backend_ports = _egress_ports(policies["allow-backend-egress"]["spec"])
    assert {6379, 443} <= backend_ports
