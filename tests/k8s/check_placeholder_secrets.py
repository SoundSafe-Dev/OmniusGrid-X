#!/usr/bin/env python3
"""Fail if production could apply a DEV placeholder credential (FS-200).

`base/` and the platform stacks deliberately ship placeholder Secrets so a
throwaway cluster is runnable out of the box. The policy was that production must
override them — but that policy lived only in READMEs, and the production overlay
in fact carried `omniusgrid_dev_secret` in `prod-s3-credentials`. A rule nothing
checks is a rule that quietly stops being true.

This reads whatever production would actually apply — the production overlay AND
the platform stacks that ci-cd.yml applies alongside it — and fails on any value
that looks like a shipped placeholder.

Usage:  ./check_placeholder_secrets.py            # checks production
        ./check_placeholder_secrets.py --staging  # same for staging
"""
from __future__ import annotations

import argparse
import subprocess
import sys

import yaml

REPO_ROOT = __file__.rsplit("/tests/", 1)[0]

# Substrings that only ever appear in a credential nobody should run in
# production. Checked case-insensitively against Secret values.
PLACEHOLDER_MARKERS = (
    "omniusgrid_dev_secret",
    "replace_me",
    "replace/me",
    "changeme",
    "change_me",
    "hooks.slack.com/services/replace",
)

# Values that are placeholders but only meaningful for specific keys — a bare
# "admin" is too generic to match blindly, so it is scoped to the key it guards.
KEYED_PLACEHOLDERS = {
    "admin-password": ("admin",),
}


def build(path: str, restrictor_none: bool = False) -> list[dict]:
    cmd = ["kustomize", "build"]
    if restrictor_none:
        cmd += ["--load-restrictor", "LoadRestrictionsNone"]
    cmd.append(f"{REPO_ROOT}/{path}")
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        print(f"error: kustomize build failed for {path}\n{out.stderr}", file=sys.stderr)
        sys.exit(2)
    return [d for d in yaml.safe_load_all(out.stdout) if d]


def offenders(docs: list[dict], source: str) -> list[str]:
    found = []
    for d in docs:
        if d.get("kind") != "Secret":
            continue
        name = d["metadata"]["name"]
        data = {**(d.get("stringData") or {}), **(d.get("data") or {})}
        for key, value in data.items():
            low = str(value).lower()
            hits = [m for m in PLACEHOLDER_MARKERS if m in low]
            hits += [
                p for p in KEYED_PLACEHOLDERS.get(key, ()) if low.strip() == p
            ]
            if hits:
                found.append(f"{source}: {name}.{key} contains {hits[0]!r}")
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staging", action="store_true", help="check staging instead")
    # The DR site is a DEPLOYED environment — arguably the one where dev
    # credentials would go unnoticed longest, since it only serves traffic during
    # an incident. It was outside this gate until overlays/dr existed (FS-230).
    ap.add_argument("--dr", action="store_true", help="check the DR overlay instead")
    args = ap.parse_args()
    env = "staging" if args.staging else ("dr" if args.dr else "production")

    # The overlay must be clean on its own — nothing filters it at apply time.
    problems: list[str] = offenders(
        build(f"infrastructure/k8s/overlays/{env}"), f"overlays/{env}"
    )

    # ci-cd.yml applies the platform stacks next to the overlay, so they are
    # equally "what this environment runs". They legitimately CONTAIN placeholders
    # (kind/dev needs them), so what matters is that the deploy pipes them through
    # strip_placeholder_secrets.py. Assert both: the filter removes them, AND the
    # workflow actually invokes it — a filter nobody calls is not enforcement.
    from strip_placeholder_secrets import is_placeholder

    for path in ("infrastructure/k8s/monitoring", "infrastructure/k8s/database-ha"):
        survivors = [d for d in build(path, True) if not is_placeholder(d)]
        problems += offenders(survivors, f"{path} (post-strip)")

    workflow = open(f"{REPO_ROOT}/.github/workflows/ci-cd.yml").read()
    if workflow.count("strip_placeholder_secrets.py") < 2:
        problems.append(
            "ci-cd.yml does not pipe BOTH platform-stack applies through "
            "tests/k8s/strip_placeholder_secrets.py — placeholder credentials "
            "would reach the cluster"
        )

    if problems:
        print(f"FAIL: {env} would apply placeholder credentials:\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nProvision real values via infrastructure/k8s/secrets/ (Sealed Secrets\n"
            "or External Secrets Operator) and remove the placeholder from what this\n"
            "environment applies — e.g. a `$patch: delete` in the overlay, as the\n"
            "production overlay does for s3-credentials.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: no placeholder credentials reachable in {env}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
