"""The README's route table must name every routed page, and no page that does not exist.

IT LISTED ELEVEN OF FORTY-ONE, and one of the eleven was `/registries` — a route the router
has never had. That is what a hand-written inventory becomes: three quarters of the app
undocumented, plus one confident entry pointing at nothing. A reader checking whether a
surface exists gets the wrong answer in both directions.

BOTH DIRECTIONS ARE CHECKED HERE, for that reason. A missing route understates the product;
a phantom route sends somebody looking for a page to write a client against. The second is
the worse failure and is the one the old table actually had.

WHY THE README AND NOT ONLY THE E2E SWEEP. `everyRouteIsSwept` already requires a route to
appear in `frontend/e2e/routes.ts`, so the *tests* cannot miss one. Nothing connected that
to the document people read first. These are different questions with the same subject —
recorded in `test_no_two_guards_keep_the_same_list.py` — because a route can be swept and
undocumented, or documented and unswept, and each is a distinct kind of wrong.

The table groups related routes on one row (`/assets`, `/assets/:id`), so this asserts that
each path STRING appears somewhere in the section rather than that each has its own row.
Grouping is a readability choice; presence is the claim.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
README = REPO / "README.md"
APP_TSX = REPO / "frontend" / "src" / "App.tsx"

SECTION_START = "### Frontend Dashboard Routes"
SECTION_END = "## Features"

#: The catch-all, which is not a page.
NOT_A_ROUTE = {"*"}


def _routed_paths() -> set[str]:
    return {
        path
        for path in re.findall(r'path="([^"]+)"', APP_TSX.read_text())
        if path not in NOT_A_ROUTE
    }


def _section() -> str:
    text = README.read_text()
    start = text.index(SECTION_START)
    return text[start: text.index(SECTION_END, start)]


class TestTheMeasurementIsReal:
    def test_the_router_is_readable(self):
        """Vacuity. If the router regex breaks, every assertion below passes over an empty
        set — which is precisely how the old table survived being three quarters wrong."""
        paths = _routed_paths()
        assert len(paths) > 30, f"only {len(paths)} routes parsed from App.tsx"
        assert "/" in paths and "/login" in paths

    def test_the_section_is_found(self):
        section = _section()
        assert len(section) > 500, "the route table section is missing or tiny"


def test_every_routed_page_is_documented():
    undocumented = sorted(p for p in _routed_paths() if f"`{p}`" not in _section())
    assert not undocumented, (
        f"{undocumented} are routed in App.tsx and appear nowhere in the README's route "
        f"table. The table listed 11 of 41 before this guard existed; a page nobody "
        f"documents is a page nobody finds."
    )


def test_no_documented_route_is_a_phantom():
    """The direction that actually bit. `/registries` sat in this table with a description
    of what it did, and there has never been such a route — the surface is `/compliance`."""
    # THE ROUTE COLUMN ONLY, not the whole section. A description legitimately names API
    # paths (`/oee/dashboard/summary`) and can even explain that a route does NOT exist —
    # the compliance row says exactly that about `/registries`. Reading the prose made both
    # of those look like claims about the router, which is the same "prose is not code"
    # mistake three other guards in this repository have each made once.
    rows = re.findall(r"^\|\s*(`/[^|]*?)\s*\|", _section(), re.M)
    documented = {path for row in rows for path in re.findall(r"`(/[^`]*)`", row)}
    routed = _routed_paths()
    phantom = sorted(path for path in documented if path not in routed)
    assert not phantom, (
        f"{phantom} are documented as pages and are not routed in App.tsx. Either the route "
        f"was removed and the row outlived it, or the row was always wrong — `/registries` "
        f"was the second kind."
    )
