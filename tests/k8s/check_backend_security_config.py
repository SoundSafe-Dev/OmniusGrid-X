#!/usr/bin/env python3
"""The backend's security-critical settings must reach the container (FS-385, FS-386).

TWO DEFECTS, FOUND TOGETHER ON 2026-08-01, AND THE SECOND IS WHY THE FIRST SURVIVED.

**The app's defaults are unsafe for a cluster.** `app/core/config.py` sets
`ALLOW_DEV_TOKEN`, `ALLOW_OPEN_REGISTRATION`, `DEBUG` and `GEOTAB_SIMULATED` to **true**
so a laptop demo works offline. Nothing in `infrastructure/k8s/` overrode any of them, so
every manifest in this repo deployed a backend that accepted the literal string
`dev-token` as an admin credential, accepted unauthenticated registrations, ran in debug,
and served randomly generated telematics as real fleet data.

**The guard against that was never armed.** `validate_settings()` hard-fails at import on
an insecure production config, and it is a good guard — ten checks, a named reason for
each. But every one sits inside `if s.ENVIRONMENT.lower() == "production"`, and
ENVIRONMENT appeared NOWHERE in any manifest or overlay. It read "development", so the
whole function returned an empty list. Measured before the fix:

    $ kustomize build infrastructure/k8s/overlays/production | grep -c ENVIRONMENT
    0

**And the ConfigMap that should have carried it was orphaned.** All three overlays
declared a `backend-config` ConfigMap; no workload had an `envFrom` anywhere, so
`LOG_LEVEL=warn` (production), `MTLS_ENABLED=false` (staging) and `DEPLOYMENT_SITE=dr`
were rendered into an object and ignored. Staging ran with mTLS on and DR logs were
unlabelled during exactly the failover they were meant to be readable in.

WHY THIS CHECKS THE BUILT MANIFESTS. Every one of these mistakes is invisible in the
sources: each file reads correctly on its own, and the defect is in what the pieces do
(or fail to do) together. It also has to survive kustomize's name-suffixing of generated
ConfigMaps, so it resolves the reference the way the kubelet would.

WHAT IT DELIBERATELY DOES NOT CHECK: that the process honours the values. That needs the
image running and belongs to k8s-smoke. This checks that the value arrives, which is the
part a manifest can get wrong on its own — and did.

Usage:  ./check_backend_security_config.py               # base + every overlay
        ./check_backend_security_config.py --path base   # one target
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = str(Path(__file__).resolve().parents[2])

DEFAULT_TARGETS = (
    "infrastructure/k8s/base",
    "infrastructure/k8s/overlays/staging",
    "infrastructure/k8s/overlays/production",
    "infrastructure/k8s/overlays/dr",
)

#: Settings that must be exactly this in every target, no exceptions. Enabling either on
#: a cluster is an authentication bypass, so no overlay is allowed to differ — which is
#: why they are pinned as explicit `env` (that beats `envFrom`) rather than offered as a
#: ConfigMap knob.
MUST_EQUAL = {
    "ALLOW_DEV_TOKEN": "false",
    "ALLOW_OPEN_REGISTRATION": "false",
}

#: Settings that must be PRESENT in every target and may legitimately differ between
#: them. Absence is the failure: an unset value silently takes the app's demo default.
MUST_BE_SET = ("ENVIRONMENT", "DEBUG", "LOG_LEVEL", "GEOTAB_SIMULATED")

#: ENVIRONMENT values that arm `validate_settings()`. Staging is allowed to opt down.
STRICT_ENVIRONMENTS = {"production"}


def build(path: str) -> list[dict]:
    result = subprocess.run(
        ["kustomize", "build", path],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"FAIL {path}: kustomize build failed\n{result.stderr}", file=sys.stderr)
        sys.exit(2)
    return [d for d in yaml.safe_load_all(result.stdout) if d]


def config_maps(docs: list[dict]) -> dict[str, dict]:
    return {
        d["metadata"]["name"]: d.get("data") or {}
        for d in docs
        if d.get("kind") == "ConfigMap"
    }


def backend_container(docs: list[dict]) -> dict | None:
    for doc in docs:
        if doc.get("kind") != "Deployment":
            continue
        spec = doc["spec"]["template"]["spec"]
        for container in spec.get("containers", []):
            # namePrefix makes this `prod-backend` / `staging-backend` etc.
            if container["name"] == "backend":
                return container
    return None


def effective_env(container: dict, maps: dict[str, dict]) -> dict[str, str]:
    """What the kubelet would put in the process environment.

    Order matters and is the whole point of one of the defects: `envFrom` is applied
    first and an explicit `env` entry of the same name WINS over it. Resolving them the
    other way round would report staging's shadowed `MTLS_ENABLED` as effective.
    """
    env: dict[str, str] = {}
    for source in container.get("envFrom", []):
        ref = source.get("configMapRef")
        if not ref:
            continue
        name = ref["name"]
        if name not in maps:
            print(
                f"  envFrom references ConfigMap '{name}', which the build does not "
                "contain — every key it was meant to carry is silently absent",
                file=sys.stderr,
            )
            sys.exit(2)
        env.update(maps[name])
    for entry in container.get("env", []):
        if "value" in entry:  # secretKeyRef/fieldRef values are not literals
            env[entry["name"]] = entry["value"]
    return env


def check(path: str) -> list[str]:
    docs = build(path)
    container = backend_container(docs)
    if container is None:
        return [f"{path}: no container named 'backend' in any Deployment"]

    env = effective_env(container, config_maps(docs))
    problems = []

    for key, expected in MUST_EQUAL.items():
        actual = env.get(key)
        if actual is None:
            problems.append(
                f"{path}: {key} is unset, so the app's default (true) applies — "
                f"{'the literal string dev-token is accepted as an admin credential' if key == 'ALLOW_DEV_TOKEN' else 'anyone can register'}"
            )
        elif actual.lower() != expected:
            problems.append(f"{path}: {key}={actual}, must be {expected}")

    for key in MUST_BE_SET:
        if key not in env:
            problems.append(
                f"{path}: {key} is unset, so the app's demo default applies silently"
            )

    environment = env.get("ENVIRONMENT", "")
    if path.endswith(("production", "dr")) and environment.lower() not in STRICT_ENVIRONMENTS:
        problems.append(
            f"{path}: ENVIRONMENT={environment!r} does not arm validate_settings(); "
            "all ten production-safety checks would be skipped"
        )
    if environment.lower() in STRICT_ENVIRONMENTS and env.get("DEBUG", "").lower() != "false":
        problems.append(f"{path}: DEBUG must be false when ENVIRONMENT is {environment}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", action="append", dest="paths")
    args = parser.parse_args()
    targets = args.paths or list(DEFAULT_TARGETS)

    all_problems = []
    for target in targets:
        problems = check(target)
        status = "FAIL" if problems else "ok  "
        print(f"{status} {target}")
        all_problems.extend(problems)

    if all_problems:
        print("\nProblems:", file=sys.stderr)
        for problem in all_problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"\n{len(targets)} targets: security-critical settings all reach the container")
    return 0


if __name__ == "__main__":
    sys.exit(main())
