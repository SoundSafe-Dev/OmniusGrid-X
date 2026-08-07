#!/usr/bin/env python3
"""Every applied manifest lands in its declared namespace and names a real target (FS-521).

THREE DEFECTS, ONE MISSING CHECK. `monitoring/`, `autoscaling/` and `database-ha/` are the
three stacks deployed outside the app overlay — they carry operator CRs and a cross-tree rule
reference, so they cannot be pulled into the image-pinned overlay build. Being outside it,
nothing ever compared them to the environment they were applied into:

  * **FS-509 — a namespace mismatch that fails the deploy.** All three hardcode
    `namespace: omniusgrid`, and the staging job piped them into
    `kubectl apply -n omniusgrid-staging`. kubectl refuses an object whose embedded namespace
    differs from `-n`, and the step runs under `set -euo pipefail`. Staging has therefore
    never had monitoring, autoscaling or the HA database applied. Production's namespace
    happened to match, which is why this survived: the broken path had no working twin to be
    compared with.

  * **FS-510 — a scale target that names nothing, in BOTH environments.** The ScaledObjects
    target `ingestion-worker`; the overlays deploy it as `staging-ingestion-worker` /
    `prod-ingestion-worker` (`namePrefix`). KEDA creates the object, reports
    `ScaledObjectCheckFailed`, and scales nothing. The three Redpanda consumer workers sat at
    a static replica count under any lag, and `ingestion-worker` is `replicas: 1` — the
    telemetry path.

  * **FS-511 — Prometheus discovering nothing.** Four scrape jobs pinned
    `namespaces: ['omniusgrid']`, so in staging Prometheus came up healthy with zero targets.
    Fixed in `prometheus-config.yml` by listing both; asserted here so it cannot narrow again.

WHY A LINT AND NOT A CLUSTER TEST. Each of these is decidable from the rendered YAML, and the
first two of them fail *at apply time* — the point where a cluster test would already be too
late to be cheap. `kubeconform` cannot see any of them: a namespace that disagrees with the
`-n` flag is schema-valid, and a `scaleTargetRef` naming an absent Deployment is a string.

Usage:  ./check_namespaces_and_targets.py
        ./check_namespaces_and_targets.py --stack monitoring
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Each platform stack, per environment: the overlay to build, the namespace every object in
#: it must carry, and the app overlay whose workloads it may reference.
ENVIRONMENTS = {
    "staging": {
        "namespace": "omniusgrid-staging",
        "app_overlay": "infrastructure/k8s/overlays/staging",
    },
    "production": {
        "namespace": "omniusgrid",
        "app_overlay": "infrastructure/k8s/overlays/production",
    },
}

STACKS = ("monitoring", "autoscaling", "database-ha")

#: Kinds that are cluster-scoped, so a namespace on them is meaningless rather than wrong.
CLUSTER_SCOPED = {
    "ClusterRole",
    "ClusterRoleBinding",
    "Namespace",
    "CustomResourceDefinition",
    "StorageClass",
    "PersistentVolume",
    "ValidatingWebhookConfiguration",
    "MutatingWebhookConfiguration",
    "PriorityClass",
}

#: Kinds whose `spec` points at a workload by name.
SCALE_TARGET_KINDS = {"ScaledObject", "HorizontalPodAutoscaler"}


def _build(path: str) -> list[dict]:
    result = subprocess.run(
        [
            "kustomize",
            "build",
            "--load-restrictor",
            "LoadRestrictionsNone",
            str(REPO_ROOT / path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"kustomize build failed for {path}:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _workload_names(docs: list[dict]) -> set[str]:
    return {
        doc["metadata"]["name"]
        for doc in docs
        if doc.get("kind") in {"Deployment", "StatefulSet", "DaemonSet"}
        and doc.get("metadata", {}).get("name")
    }


def _scale_target(doc: dict) -> str | None:
    if doc.get("kind") == "ScaledObject":
        return (doc.get("spec") or {}).get("scaleTargetRef", {}).get("name")
    if doc.get("kind") == "HorizontalPodAutoscaler":
        return (doc.get("spec") or {}).get("scaleTargetRef", {}).get("name")
    return None


def check_namespaces(problems: list[str]) -> int:
    checked = 0
    for env, config in ENVIRONMENTS.items():
        expected = config["namespace"]
        for stack in STACKS:
            path = f"infrastructure/k8s/platform/{env}/{stack}"
            if not (REPO_ROOT / path).is_dir():
                problems.append(
                    f"{path} does not exist. Every platform stack must be applied through a "
                    f"per-environment overlay that declares its namespace — applying the raw "
                    f"stack with `kubectl apply -n` is what FS-509 was."
                )
                continue
            for doc in _build(path):
                kind = doc.get("kind", "?")
                if kind in CLUSTER_SCOPED:
                    continue
                actual = doc.get("metadata", {}).get("namespace")
                checked += 1
                if actual != expected:
                    problems.append(
                        f"{path}: {kind}/{doc['metadata'].get('name')} declares "
                        f"namespace={actual!r}, expected {expected!r}. kubectl rejects an "
                        f"object whose namespace disagrees with the target, and the deploy "
                        f"step runs under `set -euo pipefail`."
                    )
    return checked


def check_scale_targets(problems: list[str]) -> int:
    checked = 0
    for env, config in ENVIRONMENTS.items():
        app_workloads = _workload_names(_build(config["app_overlay"]))
        if not app_workloads:
            problems.append(
                f"{config['app_overlay']} rendered no workloads at all; the target check "
                f"below would then pass over an empty set"
            )
            continue
        path = f"infrastructure/k8s/platform/{env}/autoscaling"
        if not (REPO_ROOT / path).is_dir():
            continue
        for doc in _build(path):
            if doc.get("kind") not in SCALE_TARGET_KINDS:
                continue
            target = _scale_target(doc)
            checked += 1
            if target not in app_workloads:
                problems.append(
                    f"{path}: {doc['kind']}/{doc['metadata']['name']} scales "
                    f"{target!r}, which {config['app_overlay']} does not deploy. The app "
                    f"overlay applies a namePrefix; the autoscaling stack does not, so the "
                    f"reference resolves to nothing and KEDA reports "
                    f"ScaledObjectCheckFailed and scales nothing. Deployed workloads: "
                    f"{sorted(app_workloads)}"
                )
    return checked


def check_prometheus_discovers_every_namespace(problems: list[str]) -> int:
    """FS-511. Four scrape jobs pinned one namespace; staging discovered nothing."""
    config_path = REPO_ROOT / "infrastructure/k8s/monitoring/prometheus-config.yml"
    config = yaml.safe_load(config_path.read_text())
    wanted = {env["namespace"] for env in ENVIRONMENTS.values()}
    checked = 0
    for job in config.get("scrape_configs", []):
        for sd in job.get("kubernetes_sd_configs") or []:
            names = set((sd.get("namespaces") or {}).get("names") or [])
            if not names:
                continue  # all-namespaces discovery is fine
            checked += 1
            missing = sorted(wanted - names)
            if missing:
                problems.append(
                    f"prometheus-config.yml: job {job.get('job_name')!r} discovers only "
                    f"{sorted(names)} and so finds no targets in {missing}. Prometheus comes "
                    f"up healthy with zero targets — the failure that looks most like "
                    f"success, because the UI is green and every rule is loaded."
                )
    return checked


def check_ci_applies_through_the_overlays(problems: list[str]) -> None:
    """The regression guard for FS-509 itself.

    Fixing the manifests without fixing the workflow leaves the mismatch exactly where it
    was, so the deploy job is checked too: no platform stack may be applied by its raw path
    with a `-n` override.
    """
    workflow = (REPO_ROOT / ".github/workflows/ci-cd.yml").read_text()
    for stack in STACKS:
        for line in workflow.splitlines():
            if f"infrastructure/k8s/{stack}" in line and "README" not in line:
                problems.append(
                    f"ci-cd.yml applies the raw stack path in: {line.strip()!r}. Build "
                    f"`infrastructure/k8s/platform/<env>/{stack}` instead — the raw stack "
                    f"hardcodes `namespace: omniusgrid` and `-n` cannot override it."
                )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", help="check one stack only")
    args = parser.parse_args()
    if args.stack:
        global STACKS
        STACKS = (args.stack,)

    problems: list[str] = []
    namespaces = check_namespaces(problems)
    targets = check_scale_targets(problems)
    jobs = check_prometheus_discovers_every_namespace(problems)
    check_ci_applies_through_the_overlays(problems)

    # Vacuity. Every check above passes trivially over an empty set, and all three read from
    # a build that can silently render nothing.
    if namespaces == 0 or targets == 0 or jobs == 0:
        print(
            f"FAIL: the checks found nothing to check "
            f"(namespaced objects={namespaces}, scale targets={targets}, pinned scrape "
            f"jobs={jobs}). Either the platform overlays are gone or the build returned "
            f"nothing — both mean this gate is protecting an empty set.",
            file=sys.stderr,
        )
        return 1

    if problems:
        print("FAIL: manifests will not apply where they are sent:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}\n", file=sys.stderr)
        return 1

    print(
        f"OK: {namespaces} namespaced objects in their declared namespace, "
        f"{targets} scale targets resolving to deployed workloads, "
        f"{jobs} scrape jobs discovering every environment"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
