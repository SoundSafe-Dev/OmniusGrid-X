#!/usr/bin/env python3
"""Filter a kustomize build stream down to just the NetworkPolicy documents.

The enforcement test applies only the policies — the probe pods stand in for the
real workloads, so nothing needs to pull an application image.

Usage:  kustomize build infrastructure/k8s/base | ./extract-netpols.py | kubectl apply -f -
"""
import sys

import yaml


def main() -> int:
    docs = [
        d
        for d in yaml.safe_load_all(sys.stdin)
        if d and d.get("kind") == "NetworkPolicy"
    ]
    if not docs:
        print("error: no NetworkPolicy documents found on stdin", file=sys.stderr)
        return 1
    yaml.safe_dump_all(docs, sys.stdout)
    print(f"extracted {len(docs)} NetworkPolicy documents", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
