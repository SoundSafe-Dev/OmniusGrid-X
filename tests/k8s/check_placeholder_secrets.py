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

Usage:  ./check_placeholder_secrets.py             # checks production
        ./check_placeholder_secrets.py --staging   # same for staging
        ./check_placeholder_secrets.py --dr        # same for the DR site
        ./check_placeholder_secrets.py --self-test # checks the matcher itself
"""
from __future__ import annotations

import argparse
import base64
import binascii
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


def _decoded(value: object) -> str:
    """A Secret value as plaintext, whichever field it arrived in.

    `stringData` is plaintext; `data` is base64 — and the markers below are plaintext,
    so matching them against an undecoded `data` value never hits. That gap mattered:
    **`secretGenerator` in a kustomization emits `data`**, which is the idiomatic way to
    create a Secret with kustomize and therefore the most likely way a placeholder
    actually reaches an overlay. Verified by injecting
    `secretGenerator: [{literals: [password=omniusgrid_dev_secret]}]` into the production
    overlay: the gate reported OK.

    Undecodable values are returned as-is rather than dropped — a value this cannot read
    should still be matched on its raw form, not silently skipped.
    """
    raw = str(value)
    try:
        return base64.b64decode(raw, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return raw


def offenders(docs: list[dict], source: str) -> list[str]:
    found = []
    for d in docs:
        if d.get("kind") != "Secret":
            continue
        name = d["metadata"]["name"]
        # Decoded, so a base64 `data:` value is checked on the same footing as a
        # plaintext `stringData:` one.
        data = {
            **{k: str(v) for k, v in (d.get("stringData") or {}).items()},
            **{k: _decoded(v) for k, v in (d.get("data") or {}).items()},
        }
        for key, value in data.items():
            low = str(value).lower()
            hits = [m for m in PLACEHOLDER_MARKERS if m in low]
            hits += [
                p for p in KEYED_PLACEHOLDERS.get(key, ()) if low.strip() == p
            ]
            if hits:
                found.append(f"{source}: {name}.{key} contains {hits[0]!r}")
    return found


def self_test() -> int:
    """Prove the matcher sees both encodings, without needing a cluster or kustomize.

    THIS EXISTS BECAUSE THE GATE PASSED A PLACEHOLDER IT SHOULD HAVE CAUGHT. Injecting

        secretGenerator:
          - name: probe
            literals: [password=omniusgrid_dev_secret]

    into the production overlay produced "OK: no placeholder credentials reachable" —
    `secretGenerator` emits base64 `data`, and the plaintext markers were compared against
    the encoded string. A gate with a blind spot over the idiomatic way to write the thing
    it guards is worse than none, because it is believed.

    Run in CI ahead of the real checks: if this fails, the OKs below mean nothing.
    """
    b64 = base64.b64encode(b"omniusgrid_dev_secret").decode()
    cases = [
        ("stringData plaintext", {"kind": "Secret", "metadata": {"name": "s"},
                                  "stringData": {"secret-key": "omniusgrid_dev_secret"}}, True),
        ("data base64 (secretGenerator)", {"kind": "Secret", "metadata": {"name": "s"},
                                           "data": {"secret-key": b64}}, True),
        ("keyed placeholder", {"kind": "Secret", "metadata": {"name": "s"},
                               "stringData": {"admin-password": "admin"}}, True),
        ("keyed placeholder, base64", {"kind": "Secret", "metadata": {"name": "s"},
                                       "data": {"admin-password":
                                                base64.b64encode(b"admin").decode()}}, True),
        ("a real credential", {"kind": "Secret", "metadata": {"name": "s"},
                               "stringData": {"secret-key": "Zr8$k2Lq9xVn"}}, False),
        ("non-base64 value is not dropped", {"kind": "Secret", "metadata": {"name": "s"},
                                             "data": {"secret-key": "replace_me!!"}}, True),
        ("not a Secret", {"kind": "ConfigMap", "metadata": {"name": "c"},
                          "data": {"secret-key": "omniusgrid_dev_secret"}}, False),
    ]
    failures = []
    for label, doc, should_flag in cases:
        flagged = bool(offenders([doc], "self-test"))
        if flagged != should_flag:
            failures.append(
                f"{label}: expected {'a hit' if should_flag else 'no hit'}, got the opposite"
            )
    if failures:
        print("FAIL: the placeholder matcher does not do what it claims:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"OK: matcher self-test passed ({len(cases)} cases, both encodings)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true",
                    help="check the matcher itself; needs no kustomize")
    ap.add_argument("--staging", action="store_true", help="check staging instead")
    # The DR site is a DEPLOYED environment — arguably the one where dev
    # credentials would go unnoticed longest, since it only serves traffic during
    # an incident. It was outside this gate until overlays/dr existed (FS-230).
    ap.add_argument("--dr", action="store_true", help="check the DR overlay instead")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
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
