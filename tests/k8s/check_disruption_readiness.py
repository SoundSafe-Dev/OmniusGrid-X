#!/usr/bin/env python3
"""Rolling deploys drain, replicas spread, and the kubelet can rank them (FS-850/851/852).

Three findings that all showed up as ZERO hits across `infrastructure/k8s/`, and all three
cost availability on ordinary days rather than during disasters.

**FS-850 — `preStop`.** When a pod is deleted, kubelet sends SIGTERM and the endpoints
controller removes the pod from its Service **in parallel**, with no ordering between
them. Endpoint removal then has to propagate to kube-proxy on every node and to the
ingress. So a container can begin shutting down while traffic is still routed to it.
`maxUnavailable: 0` does not prevent this — it governs how many replicas may be missing,
not whether a terminating one is still in rotation. The symptom is a handful of 502s on
EVERY rolling deploy: spread thin, never reproducible on demand, and easy to file as a
flaky client.

**FS-851 — `topologySpreadConstraints`.** Only backend and redpanda had anti-affinity, so
every other multi-replica workload could put all its replicas on one node. Three replicas
on one node is not high availability, and the event that takes them is a node drain — the
ordinary one, not the disaster.

**FS-852 — `PriorityClass`.** Every pod had the cluster default of zero, so under node
pressure the kubelet's ranking falls back to QoS and overshoot and cannot tell the
ingestion path from a batch export. The thing evicted is whichever pod is furthest over
its request, which is a coin toss with the live telemetry path in the draw.

WHAT THIS DOES NOT DEMAND. A `preStop` on every workload would be cargo cult: the workers
sit behind no Service — they consume from Redpanda — so there is no endpoint to propagate
and no race to lose. This checks the workloads that are actually *routed to*.

Usage:  ./check_disruption_readiness.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAYS = ["production", "staging", "dr"]

#: Workloads behind a Service that are NOT rolling-updated HTTP servers, so a preStop
#: sleep would delay every shutdown and prevent nothing. Stateful singletons whose clients
#: reconnect, and the collector, which is UDP/gRPC push rather than load-balanced pull.
NOT_ROUTED_HTTP = {
    "timescaledb", "redpanda", "redis", "seaweedfs", "jaeger", "otel-collector",
    "edge-agent",
}

#: Every priority class a workload may name. Kept here so a typo — which Kubernetes
#: accepts at apply time and then leaves the pod Pending forever — fails the build.
VALID_PRIORITIES = {"platform-critical", "platform-standard", "platform-batch"}


def _build(path: str) -> list[dict]:
    result = subprocess.run(
        ["kustomize", "build", str(REPO_ROOT / path)], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise SystemExit(f"kustomize build failed for {path}:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _strip(name: str) -> str:
    for prefix in ("prod-", "staging-", "dr-"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def main() -> int:
    problems: list[str] = []
    checked = 0

    declared = {
        doc["metadata"]["name"]
        for doc in _build("infrastructure/k8s/cluster-scoped")
        if doc.get("kind") == "PriorityClass"
    }
    if declared != VALID_PRIORITIES:
        problems.append(
            f"cluster-scoped/ declares {sorted(declared)}, expected {sorted(VALID_PRIORITIES)}. "
            f"A workload naming a class that does not exist is accepted by the API server "
            f"and then stays Pending forever."
        )

    for overlay in OVERLAYS:
        docs = _build(f"infrastructure/k8s/overlays/{overlay}")

        # A cluster-scoped object must not be duplicated per environment: `namePrefix`
        # rewrites it, so each overlay would define its own global priority scale and a
        # staging pod could outrank a production one on a shared cluster.
        for doc in docs:
            if doc.get("kind") == "PriorityClass":
                problems.append(
                    f"{overlay}: defines PriorityClass/{doc['metadata']['name']}. These "
                    f"are CLUSTER-scoped and the overlay's namePrefix renames them, so "
                    f"each environment would create its own global scale. They belong in "
                    f"infrastructure/k8s/cluster-scoped."
                )

        routed = set()
        for doc in docs:
            if doc.get("kind") == "Service":
                selector = doc["spec"].get("selector") or {}
                name = selector.get("app.kubernetes.io/name") or selector.get("app")
                if name:
                    routed.add(_strip(name))

        for doc in docs:
            if doc.get("kind") not in {"Deployment", "StatefulSet"}:
                continue
            name = _strip(doc["metadata"]["name"])
            spec = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
            checked += 1

            priority = spec.get("priorityClassName")
            if not priority:
                problems.append(
                    f"{overlay}: {name} names no priorityClassName, so under node pressure "
                    f"the kubelet cannot rank it against anything else."
                )
            elif priority not in VALID_PRIORITIES:
                problems.append(
                    f"{overlay}: {name} names priorityClassName {priority!r}, which is not "
                    f"one of {sorted(VALID_PRIORITIES)}. Kubernetes accepts an unknown "
                    f"class at apply time and the pod then never schedules."
                )

            labels = ((doc["spec"].get("template") or {}).get("metadata") or {}).get(
                "labels", {}
            )
            workload = _strip(
                labels.get("app.kubernetes.io/name") or labels.get("app") or name
            )
            if workload in routed and workload not in NOT_ROUTED_HTTP:
                containers = spec.get("containers") or []
                if not any((c.get("lifecycle") or {}).get("preStop") for c in containers):
                    problems.append(
                        f"{overlay}: {name} is behind a Service and has no preStop hook. "
                        f"SIGTERM and endpoint removal race, so a rolling deploy drops "
                        f"in-flight requests — every deploy, a few at a time."
                    )

            replicas = (doc.get("spec") or {}).get("replicas", 1)
            if replicas > 1 and not spec.get("topologySpreadConstraints"):
                if not spec.get("affinity"):
                    problems.append(
                        f"{overlay}: {name} runs {replicas} replicas with neither "
                        f"topologySpreadConstraints nor affinity, so all of them may land "
                        f"on one node and a single drain takes the workload out."
                    )

    if checked == 0:
        print("FAIL: no workloads examined — the walk is broken", file=sys.stderr)
        return 1
    if problems:
        print("\nFAIL: disruption readiness:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        return 1

    print(f"OK: {checked} workloads across {len(OVERLAYS)} overlays are drain-ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
