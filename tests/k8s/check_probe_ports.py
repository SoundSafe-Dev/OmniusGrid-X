#!/usr/bin/env python3
"""Every workload has probes, and every probe points at a port that exists (FS-262).

TWO FAILURES, AND THE SECOND IS WORSE THAN THE FIRST.

*No probe* means a wedged process — alive, loop dead — runs forever while its queue backs
up. That is what FS-214 fixed by giving the workers `/healthz` and `/readyz` through
`app/workers/health_server.py`.

*A probe pointing at a port nothing serves* is worse, because it looks like the fix. The
kubelet gets a connection refused, the probe fails, and the workload is **restart-looped by
the very thing meant to protect it** — turning a healthy deployment into CrashLoopBackOff
on a manifest that reads correctly. Nothing in `kubeconform` catches it: the YAML is
schema-valid, the port is simply wrong.

So this asserts both halves against the **built** manifests rather than the sources,
because an overlay patch can change a container's ports or its probes and the pair must
still agree after kustomize has had its say.

WHAT IT DELIBERATELY DOES NOT CHECK: whether the endpoint behind the port returns 200.
That needs the image running and belongs to `k8s-smoke`. This checks the wiring, which is
the part a manifest can get wrong on its own.

Usage:  ./check_probe_ports.py                # base + every overlay
        ./check_probe_ports.py --path base    # one target
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

# `Path(__file__).resolve()`, not the `rsplit("/tests/")` idiom used by the sibling
# scripts here: that one yields the script's own path (and so a nonsense build target)
# whenever the script is invoked by a path that does not contain "/tests/" — e.g.
# `python tests/k8s/...` from the repo root, which is how it was first run here.
REPO_ROOT = str(Path(__file__).resolve().parents[2])

#: Long-running workloads. A Job or CronJob runs to completion and is not probed.
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}

#: Targets built and checked by default — everything that can reach a cluster.
DEFAULT_TARGETS = (
    "infrastructure/k8s/base",
    "infrastructure/k8s/overlays/staging",
    "infrastructure/k8s/overlays/production",
    "infrastructure/k8s/overlays/dr",
)

#: Containers that legitimately carry no probe, with the reason. An entry here is a
#: workload nothing will restart when it wedges, so each one needs an argument.
NO_PROBE_ALLOWED = {
    # Sidecars and init-style containers that exit or have no served port.
}


def build(path: str) -> list[dict]:
    out = subprocess.run(
        ["kustomize", "build", "--load-restrictor", "LoadRestrictionsNone",
         f"{REPO_ROOT}/{path}"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        print(f"error: kustomize build failed for {path}\n{out.stderr}", file=sys.stderr)
        sys.exit(2)
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def check(docs: list[dict], source: str) -> tuple[list[str], int]:
    problems: list[str] = []
    probes_seen = 0
    for doc in docs:
        if doc.get("kind") not in WORKLOAD_KINDS:
            continue
        name = doc["metadata"]["name"]
        pod = doc["spec"]["template"]["spec"]
        for container in pod.get("containers", []):
            cname = container["name"]
            where = f"{source}: {name}/{cname}"
            declared = {
                p.get("name"): p.get("containerPort") for p in container.get("ports", [])
            }
            numbers = {v for v in declared.values() if v is not None}

            probes = {
                kind: container.get(kind)
                for kind in ("livenessProbe", "readinessProbe", "startupProbe")
                if container.get(kind)
            }
            if not probes and f"{name}/{cname}" not in NO_PROBE_ALLOWED:
                problems.append(
                    f"{where}: no probe of any kind — a wedged process here is never "
                    "restarted"
                )
                continue

            for kind, probe in probes.items():
                probes_seen += 1
                target = probe.get("httpGet") or probe.get("tcpSocket")
                if not target:
                    continue  # exec probes address no port
                port = target.get("port")
                if port in declared or port in numbers:
                    continue
                problems.append(
                    f"{where}: {kind} probes port {port!r}, which the container does "
                    f"not declare (has {declared or 'no ports'}) — the kubelet gets "
                    "connection refused and restart-loops it"
                )
    return problems, probes_seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", action="append", help="a kustomize target (repeatable)")
    args = ap.parse_args()
    targets = args.path or list(DEFAULT_TARGETS)

    problems: list[str] = []
    total_probes = 0
    for target in targets:
        found, seen = check(build(target), target)
        problems += found
        total_probes += seen

    # A guard that finds no subject passes for the wrong reason.
    if total_probes == 0:
        print(
            "FAIL: no probes found in any target. Either the traversal broke or every "
            "workload lost its probes — both are worth stopping for.",
            file=sys.stderr,
        )
        return 1

    if problems:
        print("FAIL: probe wiring is wrong:\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"OK: {total_probes} probes across {len(targets)} targets, all resolving")
    return 0


if __name__ == "__main__":
    sys.exit(main())
