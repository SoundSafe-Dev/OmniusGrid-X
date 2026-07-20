#!/usr/bin/env python3
"""Extract a single resource from a multi-document kustomize build output.

Used by the deploy jobs to apply the db-migrate Job *before* the rest of the
manifests, so migrations complete before the Deployments roll onto the new
image. `kubectl apply -k` applies everything at once, which would let new pods
serve traffic against the pre-migration schema for as long as the Job runs.

Deliberately stdlib-only (PyYAML is not guaranteed on the runner) — the parser
handles the subset of YAML that `kustomize build` emits, which is enough to
find a document's kind/name without interpreting the body.
"""
from __future__ import annotations

import argparse
import re
import sys

# `kustomize build` emits block-style YAML with two-space indents, so top-level
# keys are the only ones at column 0. That is all we need to identify a doc.
_TOP_LEVEL = re.compile(r"^([A-Za-z][A-Za-z0-9_.-]*):\s*(.*)$")


def split_documents(text: str) -> list[str]:
    """Split on YAML document separators, dropping empty documents."""
    docs = re.split(r"^---\s*$", text, flags=re.MULTILINE)
    return [d for d in docs if d.strip()]


def document_kind(doc: str) -> str | None:
    for line in doc.splitlines():
        m = _TOP_LEVEL.match(line)
        if m and m.group(1) == "kind":
            return m.group(2).strip().strip("'\"")
    return None


def document_name(doc: str) -> str | None:
    """Read metadata.name — the first `name:` nested under a `metadata:` key."""
    in_metadata = False
    for line in doc.splitlines():
        m = _TOP_LEVEL.match(line)
        if m:
            # Any new top-level key ends the metadata block.
            in_metadata = m.group(1) == "metadata"
            continue
        if in_metadata:
            stripped = line.strip()
            if stripped.startswith("name:"):
                return stripped[len("name:") :].strip().strip("'\"")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manifests", help="multi-document YAML from `kustomize build`")
    ap.add_argument("--kind", required=True, help="resource kind to extract, e.g. Job")
    ap.add_argument("--name", required=True, help="metadata.name to extract")
    ap.add_argument("--out", required=True, help="destination file")
    args = ap.parse_args()

    with open(args.manifests, encoding="utf-8") as fh:
        text = fh.read()

    matches = [
        doc
        for doc in split_documents(text)
        if document_kind(doc) == args.kind and document_name(doc) == args.name
    ]

    if not matches:
        # Fail loudly: a silently-empty migration manifest would let the deploy
        # proceed with no migrations at all, which is the exact failure this
        # script exists to prevent.
        print(
            f"error: no {args.kind}/{args.name} found in {args.manifests}",
            file=sys.stderr,
        )
        return 1
    if len(matches) > 1:
        print(
            f"error: {len(matches)} documents match {args.kind}/{args.name}",
            file=sys.stderr,
        )
        return 1

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("---\n")
        fh.write(matches[0].strip())
        fh.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
