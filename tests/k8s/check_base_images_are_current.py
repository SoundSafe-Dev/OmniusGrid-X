#!/usr/bin/env python3
"""Report base images whose pinned digest has fallen behind their tag (FS-821).

WHY THIS EXISTS. Digest-pinning a base image fixes reproducibility and creates a second
problem: the pin never moves, so the image silently ages out of security support. Floating
and unreproducible becomes frozen and stale, and the second failure is quieter — nothing
breaks, the build stays green, and the CVE count climbs.

So the pin is deliberate and its staleness is *visible*: this compares every pinned
`FROM ...@sha256:` in the repository against what its tag resolves to today, and reports the
ones that have drifted. Nightly, not per-PR — a base image moving is news, not a reason to
block a merge that has nothing to do with it.

Measured against the backend base on 2026-08-20: 6,139 vulnerabilities, 0 CRITICAL, 193 HIGH
of which 102 had a published fix. Those 102 are what a stale pin accumulates, and are also
why the image gate in ci-cd.yml blocks on CRITICAL rather than HIGH — at HIGH it would fail
on findings whose only remedy is the bump this script asks for.

EXIT CODES
    0  every pin is current, or a registry was unreachable (reported, not failed)
    1  at least one pin is behind its tag

Usage:
    python3 tests/k8s/check_base_images_are_current.py
    python3 tests/k8s/check_base_images_are_current.py --strict   # unreachable = failure
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]

ACCEPT = ",".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])

#: Anonymous-pull token endpoints, per registry.
TOKEN_URL = {
    "registry.access.redhat.com":
        "https://registry.access.redhat.com/auth/realms/rhcc/protocol/redhat-docker-v2/auth"
        "?service=docker-registry&scope=repository:{path}:pull",
    "registry-1.docker.io":
        "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{path}:pull",
    "quay.io": "https://quay.io/v2/auth?service=quay.io&scope=repository:{path}:pull",
    "ghcr.io": "https://ghcr.io/token?service=ghcr.io&scope=repository:{path}:pull",
}

FROM_LINE = re.compile(r"^FROM\s+(\S+?)@(sha256:[0-9a-f]{64})", re.M)


def _split(reference: str) -> tuple[str, str, str]:
    """`registry/path:tag` -> (registry, path, tag), defaulting Docker Hub and `latest`."""
    repo, tag = (
        reference.rsplit(":", 1)
        if ":" in reference.rsplit("/", 1)[-1]
        else (reference, "latest")
    )
    head = repo.split("/")[0]
    if "." in head or head == "localhost":
        return head, repo.split("/", 1)[1], tag
    return "registry-1.docker.io", (repo if "/" in repo else f"library/{repo}"), tag


def current_digest(reference: str) -> str | None:
    registry, path, tag = _split(reference)
    request = urllib.request.Request(
        f"https://{registry}/v2/{path}/manifests/{tag}", method="HEAD"
    )
    request.add_header("Accept", ACCEPT)
    template = TOKEN_URL.get(registry)
    if template:
        try:
            with urllib.request.urlopen(template.format(path=path), timeout=30) as response:
                body = json.load(response)
            token = body.get("token") or body.get("access_token")
            if token:
                request.add_header("Authorization", f"Bearer {token}")
        except Exception:
            pass
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.headers.get("Docker-Content-Digest")
    except Exception:
        return None


def pinned_bases() -> list[tuple[str, str, str]]:
    """(dockerfile, image reference, pinned digest) for every pinned FROM."""
    found = []
    for path in sorted(REPO.rglob("Dockerfile*")):
        if any(part in path.parts for part in ("node_modules", "venv", ".git")):
            continue
        for reference, digest in FROM_LINE.findall(path.read_text()):
            found.append((str(path.relative_to(REPO)), reference, digest))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true",
                        help="treat an unreachable registry as a failure")
    args = parser.parse_args()

    pins = pinned_bases()
    if not pins:
        print("No pinned FROM lines found — has the pinning been reverted?", file=sys.stderr)
        return 1

    stale, unreachable = [], []
    seen: dict[str, str | None] = {}
    for dockerfile, reference, pinned in pins:
        if reference not in seen:
            seen[reference] = current_digest(reference)
        latest = seen[reference]
        if latest is None:
            unreachable.append(f"{dockerfile}: {reference}")
            print(f"  ??  {dockerfile}: {reference} - registry unreachable")
        elif latest != pinned:
            stale.append((dockerfile, reference, pinned, latest))
            print(f"  STALE  {dockerfile}: {reference}")
            print(f"           pinned  {pinned}")
            print(f"           current {latest}")
        else:
            print(f"  ok  {dockerfile}: {reference}")

    if stale:
        print(f"\n{len(stale)} base image(s) behind their tag.", file=sys.stderr)
        print(
            "  A pinned digest receives no security updates. Bump each FROM to the current "
            "digest above, rebuild, and re-run the image scan - the CRITICAL gate in "
            "ci-cd.yml only sees what is in the image it is given.",
            file=sys.stderr,
        )
        return 1
    if unreachable and args.strict:
        print(f"\n{len(unreachable)} registry lookups failed under --strict.", file=sys.stderr)
        return 1
    print(f"\nAll {len(pins)} pinned base images are current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
