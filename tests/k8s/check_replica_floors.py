#!/usr/bin/env python3
"""A workload's deployed floor agrees with the floor its autoscaler declares (FS-512).

THE DEFECT. `ingestion-worker` — the live telemetry path — was `replicas: 1`, while the
autoscaler that owns it sets `minReplicaCount: 2` with its reason written out:

    # Real-time telemetry: never scale to zero (cold start would drop the live
    # stream behind), keep a warm floor and burst up on lag.

So the declared floor was 2 and the deployed floor was 1. On every apply the telemetry path
ran at a single pod until KEDA's next 15-second poll, and where KEDA is **not installed** — a
case CI explicitly tolerates, gating the autoscaling stack on the CRD existing — it stayed at
one permanently. A node drain, an image pull failure or an OOM then stopped ingestion outright.

It also had no PodDisruptionBudget, and `base/pod-disruption-budgets.yaml` states its own rule:
"Only multi-replica workloads get a PDB. Single-replica stateful pods are deliberately
excluded." By that rule the ingestion worker qualified — the rule had been applied against the
Deployment's `replicas` field, and **the floor that actually governs it lives in a different
stack, deployed by a different job.** Nothing read both.

WHAT THIS IS NOT. It is not "every workload needs a PDB". `export-worker` and
`compliance-reports-worker` have `minReplicaCount: 0` and scale to zero, where a PDB protects
nothing; timescaledb, redis, seaweedfs, jaeger and otel-collector are true singletons whose
availability needs replication, not a disruption budget — and a `minAvailable: 1` PDB on a
single-replica workload makes `kubectl drain` hang forever, which is worse than none. The
existing header argues this correctly and is left alone. The gap was only ever the workloads
whose autoscaler contradicts their manifest.

Usage:  ./check_replica_floors.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOSCALING = "infrastructure/k8s/platform/production/autoscaling"
BASE = "infrastructure/k8s/base"


def _build(path: str, permissive: bool = False) -> list[dict]:
    cmd = ["kustomize", "build"]
    if permissive:
        cmd += ["--load-restrictor", "LoadRestrictionsNone"]
    cmd.append(str(REPO_ROOT / path))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"kustomize build failed for {path}:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def main() -> int:
    base = _build(BASE)
    scaled = _build(AUTOSCALING, permissive=True)

    workloads = {
        doc["metadata"]["name"]: doc
        for doc in base
        if doc.get("kind") in {"Deployment", "StatefulSet"}
    }
    pdb_selectors = [
        (doc["spec"].get("selector") or {}).get("matchLabels", {}).get(
            "app.kubernetes.io/name"
        )
        for doc in base
        if doc.get("kind") == "PodDisruptionBudget"
    ]

    problems: list[str] = []
    checked = 0

    for doc in scaled:
        if doc.get("kind") != "ScaledObject":
            continue
        floor = (doc.get("spec") or {}).get("minReplicaCount", 0)
        if floor < 2:
            continue  # scales to zero or to one; neither wants a PDB
        checked += 1

        # The production overlay prefixes the target; the base name is what we can compare.
        target = (doc["spec"].get("scaleTargetRef") or {}).get("name", "")
        base_name = target.removeprefix("prod-").removeprefix("staging-")

        workload = workloads.get(base_name)
        if workload is None:
            problems.append(
                f"ScaledObject/{doc['metadata']['name']} holds {target!r} at a floor of "
                f"{floor}, and no workload by that name exists in {BASE}"
            )
            continue

        replicas = (workload.get("spec") or {}).get("replicas", 1)
        if replicas < floor:
            problems.append(
                f"{workload['kind']}/{base_name} declares replicas={replicas} while its "
                f"autoscaler declares minReplicaCount={floor}. Until KEDA's first poll — and "
                f"permanently in any cluster where the KEDA CRDs are absent, which CI "
                f"tolerates — the workload runs below the floor its own configuration says "
                f"it needs."
            )

        if base_name not in pdb_selectors:
            problems.append(
                f"{workload['kind']}/{base_name} is held at {floor}+ replicas by its "
                f"autoscaler and has no PodDisruptionBudget. base/pod-disruption-budgets.yaml "
                f"states the rule — only multi-replica workloads get one — but applies it "
                f"against the Deployment's `replicas` field, and the floor that governs this "
                f"workload lives in the autoscaling stack."
            )

    if checked == 0:
        print(
            "FAIL: no ScaledObject declares a floor of 2 or more, so this gate checked "
            "nothing. Either the autoscaling stack is gone or the build rendered nothing.",
            file=sys.stderr,
        )
        return 1

    if problems:
        print("FAIL: a workload runs below its own declared floor:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        return 1

    print(
        f"OK: {checked} workload(s) with an autoscaler floor of 2+, each deployed at or "
        f"above it and covered by a PodDisruptionBudget"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
