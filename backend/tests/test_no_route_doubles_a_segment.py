"""No route repeats a path segment (FS-468).

A router that declares `prefix="/logistics"` and is then mounted at `/api/v1/logistics`
serves everything at `/api/v1/logistics/logistics/…`. Nothing fails: the routes exist, they
are reachable, and their tests pass because the tests were written against whatever the app
actually served. The only casualties are the people who read the documentation, try the
documented path, and get a 404.

It has happened three times here — `yard`, `transportation`, and `logistics_correlation`,
which stayed doubled longest because removing its prefix would have collided with
`fleet_logistics` on two paths, and picking a winner was a decision nobody had made.

WHY A SEGMENT-REPEAT CHECK RATHER THAN A LIST OF KNOWN ROUTERS. The defect is produced by
the *combination* of a router's own prefix and its mount point, which are written in two
files by two people at two times. Neither is wrong alone. What is checkable is the shape
that combination produces, and the shape is visible on the finished route.

WHAT IT DELIBERATELY ALLOWS. A repeat that is not adjacent — `/api/v1/assets/{id}/assets`
would be odd but is not this defect — and a path parameter that happens to echo its
collection. Only an immediately doubled literal segment is flagged, because that is what a
prefix collision produces and nothing else does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import app  # noqa: E402
from _route_tree import http_routes  # noqa: E402

#: Routes whose doubling is intentional, with the reason. Empty, and the intention is that
#: it stays that way — an entry here should be rare enough to argue about.
ALLOWED: dict[str, str] = {}


def _paths() -> list[str]:
    return sorted({path for _route, path, _methods in http_routes(app)})


def _doubled(path: str) -> str | None:
    """The repeated segment, if two adjacent literal segments are identical."""
    segments = [s for s in path.split("/") if s]
    for first, second in zip(segments, segments[1:]):
        if first == second and not first.startswith("{"):
            return first
    return None


class TestTheSweepCanSeeItsSubject:
    def test_it_finds_the_routes(self):
        paths = _paths()
        assert len(paths) > 200, (
            f"only {len(paths)} routes found; the walk is broken and the assertion below "
            f"would pass over nothing"
        )

    def test_the_detector_recognises_the_shape(self):
        """The pattern itself, asserted — a narrowed detector reports clean forever."""
        assert _doubled("/api/v1/logistics/logistics/load-quality") == "logistics"
        assert _doubled("/api/v1/yard/yard/trailers") == "yard"
        # And must NOT fire on the normal cases, or every route becomes an offender.
        assert _doubled("/api/v1/logistics/load-quality") is None
        assert _doubled("/api/v1/assets/{asset_id}/telemetry") is None
        assert _doubled("/api/v1/registries/{registry_id}/items") is None


def test_no_route_repeats_an_adjacent_segment():
    offenders = []
    for path in _paths():
        segment = _doubled(path)
        if segment and path not in ALLOWED:
            offenders.append(f"{path}  (segment {segment!r} appears twice)")

    assert not offenders, (
        "these routes repeat a path segment, which is what a router prefix colliding with "
        "its mount point produces:\n  "
        + "\n  ".join(offenders)
        + "\n\nEither the router declares a prefix it does not need, or main.py mounts it "
        "somewhere that already includes it. Nothing fails on its own — the routes work, "
        "and only the documented path 404s."
    )


def test_the_two_logistics_implementations_no_longer_collide():
    """The specific resolution, pinned (FS-468).

    `fleet_logistics` is canonical for `/delivery-efficiency` and `/compliance/summary`:
    response models, the HOS fix that stopped an unreported driver counting as compliant,
    and the paths `transportation.ts` actually calls. The correlation variants answer a
    different question — they take a `days` window — and live under `/correlation/`.

    Asserted because the fix is a NAMING decision, and a later tidy-up that renamed them
    back would restore a collision in which whichever router registers first silently wins.
    """
    paths = set(_paths())
    for canonical in (
        "/api/v1/logistics/delivery-efficiency",
        "/api/v1/logistics/compliance/summary",
    ):
        assert canonical in paths, f"{canonical} is no longer served by fleet_logistics"
    for variant in (
        "/api/v1/logistics/correlation/delivery-efficiency",
        "/api/v1/logistics/correlation/compliance-summary",
    ):
        assert variant in paths, (
            f"{variant} is missing; if the correlation variant was renamed back it now "
            f"collides with fleet_logistics, and the winner is decided by registration "
            f"order rather than by anyone"
        )
