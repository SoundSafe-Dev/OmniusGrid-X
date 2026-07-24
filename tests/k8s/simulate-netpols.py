#!/usr/bin/env python3
"""Offline NetworkPolicy evaluator for the enforcement matrix.

Evaluates the same client->server pairs `netpol-test.sh` asserts, but against the
policy YAML directly — no cluster needed. Used to sanity-check that the matrix's
expectations match what the policies actually encode BEFORE burning a CI run, and
to prove a regression would be caught (see `--expect-fail`).

Kubernetes semantics implemented: a connection is allowed only if the CLIENT's
egress permits it (or no Egress policy selects the client) AND the SERVER's
ingress permits it (or no Ingress policy selects the server).

Usage:
  kustomize build ... | ./extract-netpols.py > policies.yaml
  ./simulate-netpols.py policies.yaml probe.yaml matrix.tsv
"""
import sys

import yaml


def sel_matches(sel, labels):
    """podSelector match (matchLabels + matchExpressions In/NotIn/Exists)."""
    if sel is None:
        return False
    for k, v in (sel.get("matchLabels") or {}).items():
        if labels.get(k) != v:
            return False
    for e in sel.get("matchExpressions") or []:
        val, op = labels.get(e["key"]), e["operator"]
        if op == "In" and val not in e["values"]:
            return False
        if op == "NotIn" and val in e["values"]:
            return False
        if op == "Exists" and val is None:
            return False
        if op == "DoesNotExist" and val is not None:
            return False
    return True


def ns_matches(sel, ns_labels):
    return sel_matches(sel, ns_labels)


def selects(policy, pod):
    """Does this policy apply to the pod (same namespace + podSelector match)?"""
    return policy["metadata"].get("namespace", "default") == pod["ns"] and sel_matches(
        policy["spec"]["podSelector"], pod["labels"]
    )


def peer_allows(rules, key, peer, port):
    """Any rule whose ports include `port` and whose peers match `peer`."""
    for r in rules or []:
        ports = r.get("ports")
        # No ports field means "all ports".
        if ports is not None and not any(p.get("port") == port for p in ports):
            continue
        peers = r.get(key)
        # No peer field means "all sources/destinations".
        if peers is None:
            return True
        for p in peers:
            pod_ok = "podSelector" not in p or sel_matches(p["podSelector"], peer["labels"])
            ns_ok = "namespaceSelector" not in p or ns_matches(
                p["namespaceSelector"], peer["ns_labels"]
            )
            # An entry with only a podSelector is same-namespace-only.
            if "namespaceSelector" not in p and peer["ns"] != r.get("_policy_ns"):
                continue
            if "ipBlock" in p:
                continue
            if pod_ok and ns_ok:
                return True
    return False


def verdict(policies, client, server, port):
    egress = [p for p in policies if selects(p, client) and "Egress" in p["spec"]["policyTypes"]]
    ingress = [p for p in policies if selects(p, server) and "Ingress" in p["spec"]["policyTypes"]]

    def check(pols, key, peer):
        if not pols:
            return True  # no policy selects this pod for this direction -> allowed
        for p in pols:
            rules = p["spec"].get(key)
            for r in rules or []:
                r["_policy_ns"] = p["metadata"].get("namespace", "default")
            if peer_allows(rules, "to" if key == "egress" else "from", peer, port):
                return True
        return False

    return check(egress, "egress", server) and check(ingress, "ingress", client)


def main() -> int:
    policies = [d for d in yaml.safe_load_all(open(sys.argv[1])) if d]
    probes = [d for d in yaml.safe_load_all(open(sys.argv[2])) if d]

    ns_labels = {
        ns: {"kubernetes.io/metadata.name": ns}
        for ns in {p["metadata"].get("namespace", "default") for p in probes}
    }
    pods = {
        p["metadata"]["name"]: {
            "ns": p["metadata"].get("namespace", "default"),
            "labels": p["metadata"].get("labels", {}),
            "ns_labels": ns_labels[p["metadata"].get("namespace", "default")],
        }
        for p in probes
    }

    rc = 0
    for line in open(sys.argv[3]):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, cpod, spod, port, expect = line.split("\t")
        got = "ALLOW" if verdict(policies, pods[cpod], pods[spod], int(port)) else "DENY"
        ok = got == expect
        print(f"{name:24} expect={expect:5} got={got:5} {'ok' if ok else 'MISMATCH'}")
        if not ok:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
