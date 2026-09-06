"""The source trees this repository's sweeps walk, declared once (FS-982).

Four separate guards had each written out "backend/app and edge-agent/opsgrid_agent" as
their own module constant — `CODE_ROOTS` in
`test_every_alert_watches_a_series_something_exports.py`, `ROOTS` in
`test_no_unapproved_primitive_is_reachable.py`, `SEARCH_ROOTS` (a wider set) in
`test_the_session_arc_is_a_real_range.py`, and `TREES` in the new
`test_nothing_swallows_baseexception.py`. `test_no_two_guards_keep_the_same_list.py`
caught the fourth and asked the right question: derive one from the other, or say why the
overlap is two questions rather than one fact written twice.

It is one fact. A new top-level Python package — a second agent, a worker split out of the
backend — would need finding in four places, and the failure mode is silent: a sweep that
walks three of the four trees still passes, just over less than it claims.

WHY BOTH ARE OFFERED. `PACKAGE_ROOTS` is the shipped application code, which is what a
"does any of our code do X" sweep means. `ALL_ROOTS` adds tests, frontend and docs, which is
what a "does this string appear anywhere" sweep means. They are different questions, and
naming both here is what stops the next guard from inventing a third spelling of either.

ALL FOUR ARE MIGRATED, including the three that predate this file. Deferring them was the
first instinct -- each is load-bearing for a different guard -- but
`test_no_two_guards_keep_the_same_list.py` then flagged this file against the three it was
meant to replace, which is the correct reading: a fifth copy that merely *offers* to be the
single declaration is still a fifth copy. The risk of moving four sweeps at once is that one
quietly starts walking a different set, so each was checked before and after by comparing
the resolved paths as a set, not by trusting that the literals looked the same.
"""
from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Shipped application code — the Python packages this repository deploys.
PACKAGE_ROOTS = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "edge-agent" / "opsgrid_agent",
)

#: Everything a text-level sweep might legitimately search, application code included.
ALL_ROOTS = PACKAGE_ROOTS + (
    REPO_ROOT / "backend" / "tests",
    REPO_ROOT / "edge-agent" / "tests",
    REPO_ROOT / "frontend" / "src",
    REPO_ROOT / "docs",
)
