#!/usr/bin/env python3
"""The k8s README names every directory the tree can build (FS-520).

THE DEFECT. `infrastructure/k8s/README.md` opens by calling the tree **canonical** and then
listed `base/` and two overlays. `overlays/dr` has existed since FS-230, is built and validated
by five CI gates, and appeared nowhere in it.

A directory that CI builds and the canonical document does not name is worse than an undocumented
one, because the document is complete on its face. An operator reads it, concludes the tree is
`base/` plus two overlays, and either misses the DR site entirely or — having found it — stops
trusting anything else the file says. **Documentation is only load-bearing while it is
exhaustive; the first omission removes the weight from all of it.**

WHY A LINT AND NOT A PROOFREAD. The gap opened by addition, not by edit: somebody added a
directory and did not think of a README two levels up. That is not a thing review catches
reliably, and it recurs — this same commit added six directories under `platform/`, and five of
them would have gone unnamed by exactly the same route.

WHAT IT DOES NOT CHECK. Whether the description is *accurate*. A table row can be as wrong as
any other prose. What it can enforce is that no buildable tree is missing, which is the failure
that actually happened.

Usage:  ./check_the_readme_describes_the_tree.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
K8S = REPO_ROOT / "infrastructure" / "k8s"
README = K8S / "README.md"

#: Buildable directories deliberately left out, with why. Empty is the target state.
NOT_DESCRIBED: dict[str, str] = {}


def main() -> int:
    buildable = sorted(
        str(path.parent.relative_to(K8S))
        for path in K8S.rglob("kustomization.yaml")
    )
    if not buildable:
        print(
            "FAIL: no kustomization.yaml found under infrastructure/k8s. The traversal is "
            "broken and this gate would pass over an empty set.",
            file=sys.stderr,
        )
        return 1

    text = README.read_text()
    missing = [
        directory
        for directory in buildable
        if directory not in text and directory not in NOT_DESCRIBED
    ]

    if missing:
        print(
            "FAIL: the canonical README does not name every buildable tree:\n",
            file=sys.stderr,
        )
        for directory in missing:
            print(
                f"  - {directory}/ has a kustomization.yaml and CI builds it, and "
                f"infrastructure/k8s/README.md never mentions it. The file opens by calling "
                f"the tree canonical, so an omission reads as an absence.\n",
                file=sys.stderr,
            )
        return 1

    stale = sorted(set(NOT_DESCRIBED) - set(buildable))
    if stale:
        print(
            f"FAIL: {stale} are excused in NOT_DESCRIBED and no longer build. Delete the "
            f"entries — they describe nothing.",
            file=sys.stderr,
        )
        return 1

    print(f"OK: all {len(buildable)} buildable trees are named in the canonical README")
    return 0


if __name__ == "__main__":
    sys.exit(main())
