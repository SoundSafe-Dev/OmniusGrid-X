#!/usr/bin/env python3
"""The namespace quota is above what its own replica ceilings demand (FS-849).

`ResourceQuota` and `LimitRange` returned zero hits across `infrastructure/k8s/`. Every
workload declared its own requests and limits, which is necessary and not sufficient:
per-container declarations cannot bound what the ceilings ADD UP TO. The backend HPA
allows 20 replicas and KEDA allows 12 + 8 + 6 workers, so a runaway scale-out could
consume the cluster and starve the namespaces that would report it — monitoring, ingress,
cert-manager. An application fault reaching the control plane is a blast radius nobody
chose.

WHY THIS CHECK EXISTS RATHER THAN JUST THE QUOTA. A quota is a number in a file next to
other numbers in other files, and the two drift in the direction that hurts: raising
`maxReplicas` is a one-line change that silently makes the quota too small, and the
symptom appears only under the load that needed the extra replicas. Once `requests.cpu` is
exhausted the namespace stops admitting pods, so the HPA scales up and the new replicas
sit **Pending** — the platform stops responding to load in exactly the way it was scaled
to handle, and the quota that was meant to contain a fault has caused one.

So the demand is recomputed from the manifests on every build and compared to the quota.
Raising a replica ceiling without raising the quota fails here rather than at 3am.

Usage:  ./check_resource_quota_fits.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

ENVIRONMENTS = [
    ("infrastructure/k8s/overlays/production",
     "infrastructure/k8s/platform/production/autoscaling", "production"),
    ("infrastructure/k8s/overlays/staging",
     "infrastructure/k8s/platform/staging/autoscaling", "staging"),
    ("infrastructure/k8s/overlays/dr", None, "dr"),
]

WORKLOADS = {"Deployment", "StatefulSet", "Job", "CronJob"}


def _cpu(value) -> float:
    """Kubernetes CPU to cores. `500m` is half a core; a bare number is whole cores."""
    if value is None:
        return 0.0
    text = str(value)
    return float(text[:-1]) / 1000 if text.endswith("m") else float(text)


def _memory(value) -> float:
    """Kubernetes memory to MiB, honouring both binary and decimal suffixes."""
    if value is None:
        return 0.0
    text = str(value)
    for suffix, multiplier in (("Gi", 1024), ("Mi", 1), ("Ki", 1 / 1024),
                               ("G", 1000), ("M", 1), ("K", 1 / 1000)):
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * multiplier
    return float(text) / (1024 * 1024)  # bare bytes


def _build(path: str, permissive: bool = False) -> list[dict]:
    cmd = ["kustomize", "build"]
    if permissive:
        cmd += ["--load-restrictor", "LoadRestrictionsNone"]
    cmd.append(str(REPO_ROOT / path))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"kustomize build failed for {path}:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _strip_prefix(name: str) -> str:
    for prefix in ("prod-", "staging-", "dr-"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _pod_spec(doc: dict) -> dict:
    spec = doc.get("spec") or {}
    template = spec.get("template")
    if template is None:
        template = ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template")
    return ((template or {}).get("spec")) or {}


def _ceilings(docs: list[dict], scaled: list[dict]) -> dict[str, int]:
    """Max replicas per workload: the autoscaler's ceiling where one exists."""
    ceilings: dict[str, int] = {}
    for doc in docs:
        if doc.get("kind") in {"Deployment", "StatefulSet"}:
            ceilings[_strip_prefix(doc["metadata"]["name"])] = (
                doc.get("spec") or {}
            ).get("replicas", 1)
        elif doc.get("kind") in {"Job", "CronJob"}:
            ceilings[_strip_prefix(doc["metadata"]["name"])] = 1
    for doc in scaled:
        spec = doc.get("spec") or {}
        target = _strip_prefix((spec.get("scaleTargetRef") or {}).get("name", ""))
        if doc.get("kind") == "ScaledObject":
            ceilings[target] = max(ceilings.get(target, 0), spec.get("maxReplicaCount", 1))
        elif doc.get("kind") == "HorizontalPodAutoscaler":
            ceilings[target] = max(ceilings.get(target, 0), spec.get("maxReplicas", 1))
    return ceilings


def main() -> int:
    problems: list[str] = []
    checked = 0

    for overlay, autoscaling, label in ENVIRONMENTS:
        docs = _build(overlay)
        scaled = _build(autoscaling, permissive=True) if autoscaling else []
        scaled += [d for d in docs if d.get("kind") == "HorizontalPodAutoscaler"]
        ceilings = _ceilings(docs, scaled)

        quota = next((d for d in docs if d.get("kind") == "ResourceQuota"), None)
        if quota is None:
            problems.append(
                f"{label}: no ResourceQuota. The namespace total is unbounded, so a "
                f"runaway scale-out can consume the cluster and starve monitoring and "
                f"ingress — the namespaces that would tell you it is happening."
            )
            continue
        if not any(d.get("kind") == "LimitRange" for d in docs):
            problems.append(
                f"{label}: no LimitRange. A workload added without `resources` is "
                f"admitted unbounded and silently consumes the quota."
            )

        demand = {"requests.cpu": 0.0, "requests.memory": 0.0,
                  "limits.cpu": 0.0, "limits.memory": 0.0}
        pods = 0
        for doc in docs:
            if doc.get("kind") not in WORKLOADS:
                continue
            replicas = ceilings.get(_strip_prefix(doc["metadata"]["name"]), 1)
            pods += replicas
            for container in _pod_spec(doc).get("containers") or []:
                resources = container.get("resources") or {}
                for section, key in (("requests", "requests"), ("limits", "limits")):
                    values = resources.get(section) or {}
                    demand[f"{key}.cpu"] += _cpu(values.get("cpu")) * replicas
                    demand[f"{key}.memory"] += _memory(values.get("memory")) * replicas

        if pods == 0:
            problems.append(
                f"{label}: no workloads found. The traversal is broken and this check "
                f"would pass on an empty demand."
            )
            continue

        checked += 1
        hard = (quota.get("spec") or {}).get("hard") or {}
        print(
            f"  {label:<11} demand {demand['requests.cpu']:.1f} CPU / "
            f"{demand['requests.memory']/1024:.1f} Gi requested, {pods} pods"
        )

        for key, actual, to_number, unit in (
            ("requests.cpu", demand["requests.cpu"], _cpu, "CPU"),
            ("requests.memory", demand["requests.memory"], _memory, "MiB"),
            ("limits.cpu", demand["limits.cpu"], _cpu, "CPU"),
            ("limits.memory", demand["limits.memory"], _memory, "MiB"),
        ):
            allowed = to_number(hard.get(key))
            if allowed and actual > allowed:
                problems.append(
                    f"{label}: workloads at their declared replica ceilings need "
                    f"{actual:.1f} {unit} of {key}, and the ResourceQuota allows "
                    f"{allowed:.1f}. Once that is exhausted the namespace stops admitting "
                    f"pods, so the autoscaler scales up and the new replicas sit Pending "
                    f"— the platform stops responding to load in exactly the way it was "
                    f"scaled to handle."
                )

        allowed_pods = float(hard.get("pods", 0) or 0)
        if allowed_pods and pods > allowed_pods:
            problems.append(
                f"{label}: replica ceilings total {pods} pods against a quota of "
                f"{allowed_pods:.0f}."
            )

    if checked == 0:
        print("FAIL: no environment was measured — the walk is broken", file=sys.stderr)
        return 1
    if problems:
        print("\nFAIL: the namespace quota does not fit its own ceilings:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        return 1

    print(f"OK: {checked} namespaces are bounded above their declared ceilings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
