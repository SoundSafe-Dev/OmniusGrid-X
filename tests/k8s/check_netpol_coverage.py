#!/usr/bin/env python3
"""Every workload in a default-deny namespace must be covered by a policy (FS-227).

WHY THIS EXISTS. "The policy exists but does not cover it" has now bitten this
repo four times:

  1. CNPG WAL archiving to S3 — egress opened for the export worker but not for
     the database, so backups silently failed.
  2. prometheus -> worker :9109 — the worker's ingress rule was added and the
     scrape still failed, because Prometheus's own egress did not list the port.
  3. backend -> cnpg :5432 — egress named `timescaledb` only, so adopting the HA
     cluster broke every query.
  4. otel-collector and jaeger — deployed into a namespace with
     `default-deny-all` and given NO policy at all. Tracing was completely dead
     and nothing anywhere errored.

Every one of these is the same shape: a `default-deny-all` with `podSelector: {}`
means the DEFAULT is "no traffic", so forgetting a rule does not fail loudly. It
produces a component that starts, reports healthy, and does nothing.

The enforcement matrix (netpol-test.sh / simulate-netpols.py) catches paths someone
thought to write a case for. This catches the case nobody thought of, which is the
one that keeps happening: it walks every Deployment/StatefulSet in a namespace that
carries a default-deny and asserts each is selected by at least one Ingress policy
and one Egress policy.

DELIBERATE LIMIT. This proves a workload is not *entirely* cut off. It does NOT
prove the rules name the right ports or peers — that is what the matrix is for.
The two gates are complementary: this one is broad and shallow, the matrix is
narrow and exact. Neither replaces the other, and saying so matters, because a
green run here does not mean "networking is correct".

Usage:
    kustomize build <dir> | ./tests/k8s/check_netpol_coverage.py
    ./tests/k8s/check_netpol_coverage.py < rendered.yaml
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Set, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("pyyaml is required: pip install pyyaml")

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet"}

# Workloads that legitimately need no policy of their own, with the reason. An
# exemption must be justified here rather than silently skipped — the whole point
# of this gate is that silence is the failure mode.
EXEMPT: Dict[str, str] = {}


def _labels_match(selector: Dict[str, Any], labels: Dict[str, str]) -> bool:
    """Does a Kubernetes labelSelector match this label set?

    An empty selector (`{}`) matches everything — that is what makes
    `default-deny-all` apply to every pod, and it is also why an empty selector
    cannot be counted as coverage (see `_covering_policies`).
    """
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expr in selector.get("matchExpressions") or []:
        key, op = expr.get("key"), expr.get("operator")
        values = expr.get("values") or []
        actual = labels.get(key)
        if op == "In" and actual not in values:
            return False
        if op == "NotIn" and actual in values:
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
    return True


def _is_default_deny(policy: Dict[str, Any]) -> bool:
    """A policy that selects everything and permits nothing."""
    spec = policy.get("spec") or {}
    selector = spec.get("podSelector")
    if selector != {} and selector is not None and (
        selector.get("matchLabels") or selector.get("matchExpressions")
    ):
        return False
    return not spec.get("ingress") and not spec.get("egress")


def main() -> int:
    docs = [d for d in yaml.safe_load_all(sys.stdin) if d]

    workloads: List[Tuple[str, str, str, Dict[str, str]]] = []
    policies: List[Dict[str, Any]] = []

    for doc in docs:
        kind = doc.get("kind")
        meta = doc.get("metadata") or {}
        ns = meta.get("namespace", "default")
        if kind in WORKLOAD_KINDS:
            template = (
                (doc.get("spec") or {}).get("template") or {}
            ).get("metadata") or {}
            workloads.append((kind, meta.get("name", "?"), ns, template.get("labels") or {}))
        elif kind == "NetworkPolicy":
            policies.append(doc)

    # Only namespaces that actually default-deny are in scope. Elsewhere the
    # default is "allow", so an uncovered workload is not cut off.
    deny_namespaces: Set[str] = {
        (p.get("metadata") or {}).get("namespace", "default")
        for p in policies
        if _is_default_deny(p)
    }

    if not deny_namespaces:
        print("no default-deny namespace in this render; nothing to check")
        return 0

    failures: List[str] = []
    checked = 0

    for kind, name, ns, labels in workloads:
        if ns not in deny_namespaces:
            continue
        if name in EXEMPT:
            print(f"  EXEMPT  {kind}/{name}: {EXEMPT[name]}")
            continue
        checked += 1

        covering = {"Ingress": [], "Egress": []}
        for policy in policies:
            pmeta = policy.get("metadata") or {}
            if pmeta.get("namespace", "default") != ns:
                continue
            if _is_default_deny(policy):
                # The deny itself "selects" everything but permits nothing, so
                # counting it as coverage would make this gate always pass.
                continue
            spec = policy.get("spec") or {}
            if not _labels_match(spec.get("podSelector") or {}, labels):
                continue
            for direction in ("Ingress", "Egress"):
                rules = spec.get(direction.lower())
                if direction in (spec.get("policyTypes") or []) and rules:
                    covering[direction].append(pmeta.get("name"))

        for direction in ("Ingress", "Egress"):
            if not covering[direction]:
                failures.append(
                    f"{kind}/{name} (ns={ns}) has NO {direction} policy — "
                    f"default-deny-all applies, so this workload is cut off in "
                    f"that direction and will fail silently"
                )
        if covering["Ingress"] and covering["Egress"]:
            print(
                f"  OK      {kind}/{name}: "
                f"in={','.join(sorted(set(covering['Ingress'])))} "
                f"out={','.join(sorted(set(covering['Egress'])))}"
            )

    print(
        f"\nchecked {checked} workload(s) in default-deny namespace(s) "
        f"{sorted(deny_namespaces)}"
    )
    if failures:
        print("\nFAIL — uncovered workloads:")
        for f in failures:
            print(f"  * {f}")
        print(
            "\nAdd the missing rule, or add an EXEMPT entry in this script with the "
            "reason. Note this gate only proves a workload is not entirely cut off; "
            "the enforcement matrix (netpol-test.sh) proves the ports and peers."
        )
        return 1

    print("OK: every workload is covered in both directions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
