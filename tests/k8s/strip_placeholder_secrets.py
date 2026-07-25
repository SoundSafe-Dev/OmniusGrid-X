#!/usr/bin/env python3
"""Drop placeholder Secrets from a manifest stream before applying it (FS-200).

`monitoring/` and `database-ha/` ship placeholder credentials so a kind or dev
cluster runs out of the box. Production must not apply those — it provisions real
ones via `infrastructure/k8s/secrets/` (Sealed Secrets or ESO) instead.

Rather than duplicating both stacks into "-production" variants, the production
deploy pipes them through this filter. Dropping the Secret is deliberately LOUD in
its consequence: if the real one was never provisioned, the dependent pod fails to
start with CreateContainerConfigError — which is far better than Grafana silently
coming up on the password `admin`, or Alertmanager posting to a REPLACE/ME webhook.

Usage:
  kustomize build … | ./strip_placeholder_secrets.py | kubectl apply -f -
"""
from __future__ import annotations

import sys

import yaml

from check_placeholder_secrets import KEYED_PLACEHOLDERS, PLACEHOLDER_MARKERS


def is_placeholder(doc: dict) -> bool:
    if doc.get("kind") != "Secret":
        return False
    data = {**(doc.get("stringData") or {}), **(doc.get("data") or {})}
    for key, value in data.items():
        low = str(value).lower()
        if any(m in low for m in PLACEHOLDER_MARKERS):
            return True
        if low.strip() in KEYED_PLACEHOLDERS.get(key, ()):
            return True
    return False


def main() -> int:
    docs = [d for d in yaml.safe_load_all(sys.stdin) if d]
    kept, dropped = [], []
    for d in docs:
        (dropped if is_placeholder(d) else kept).append(d)

    for d in dropped:
        print(
            f"STRIPPED placeholder Secret {d['metadata']['name']} — production must "
            "provision the real value (infrastructure/k8s/secrets/)",
            file=sys.stderr,
        )
    if not dropped:
        print("no placeholder Secrets in this stream", file=sys.stderr)

    yaml.safe_dump_all(kept, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
