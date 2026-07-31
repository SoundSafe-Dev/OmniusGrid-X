"""The rag-indexing worker is deployed exactly once, with its RAG wiring.

Mirrors test_ota_worker_topology.py. The critical assertion is the compose
`rag` profile: qdrant/seaweedfs/rag-inference are all profiled, so a worker
without it would start with no dependencies present.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_map(container):
    return {item["name"]: item.get("value") for item in container["env"]}


def test_compose_service_is_profiled_and_needs_no_redpanda():
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    worker = compose["services"]["rag-indexing-worker"]

    assert worker["command"] == "python -m app.workers.rag_indexing"
    assert worker["profiles"] == ["rag"], (
        "qdrant/seaweedfs/rag-inference are profiled; the worker must match"
    )
    assert "redpanda" not in worker["depends_on"], (
        "the DB-queue design must not reintroduce a Kafka dependency"
    )
    assert worker["depends_on"]["migrate"] == {
        "condition": "service_completed_successfully"
    }
    required = {
        "DATABASE_URL", "S3_ENDPOINT_URL", "QDRANT_URL", "RAG_INFERENCE_URL",
        "RAG_INDEX_WORKER_ENABLED", "RAG_INDEX_POLL_INTERVAL_SECONDS",
        "RAG_INDEX_MAX_ATTEMPTS", "RAG_INDEX_STALE_INDEXING_SECONDS",
    }
    assert required <= set(worker["environment"])


def test_k8s_deployment_registered_once_with_rag_namespace_fqdns():
    base = REPO_ROOT / "infrastructure/k8s/base"
    kustomization = yaml.safe_load((base / "kustomization.yaml").read_text())
    assert kustomization["resources"].count(
        "rag-indexing-worker-deployment.yaml"
    ) == 1

    manifest = yaml.safe_load(
        (base / "rag-indexing-worker-deployment.yaml").read_text()
    )
    container = manifest["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == ["python", "-m", "app.workers.rag_indexing"]

    env = _env_map(container)
    assert env["QDRANT_URL"].endswith("qdrant.omniusgrid-rag.svc.cluster.local:6333")
    assert env["S3_ENDPOINT_URL"].endswith(
        "seaweedfs.omniusgrid-rag.svc.cluster.local:8333"
    )
    assert env["SCHEDULERS_IN_API"] == "false"

    security = container["securityContext"]
    assert security["allowPrivilegeEscalation"] is False
    assert security["readOnlyRootFilesystem"] is True
