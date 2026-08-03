"""The README's test count must not be a thousand short (FS-402).

It said **2,149 tests**. Collection reports 3,191. The number was true when written, nobody
was wrong to write it, and it rotted quietly for weeks — in the flattering direction for a
reader deciding whether this codebase is tested, which is the direction that gets quoted.

`test_ci_gate_count_is_accurate.py` already does this for the CI job counts and its header
puts the case: "A count in prose has no way to notice that jobs were added, and a stale
number in the most-read file in the repo is worse than no number: it is the figure someone
quotes to a customer."

WHY A FLOOR AND NOT THE EXACT NUMBER. A job count changes a few times a year; a test count
changes several times a day, and an exact assertion would fail on every commit that adds a
test — which trains people to edit the number without reading it, the same reflex that let
2,149 survive. A floor only fails when the prose has become a LIE, which is the only time
anyone needs to act.

The floor is deliberately close to the real figure. Set far below it — "500+ tests" — this
passes forever and asserts nothing, so `test_the_floor_is_not_meaninglessly_low` keeps the
claim within reach of the truth from the other side.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
README = REPO / "README.md"
BACKEND = REPO / "backend"

#: `**3,200+ tests**` in the CI-safety table.
CLAIM = re.compile(r"\*\*([\d,]+)\+ tests\*\*")

#: `all 470 documented operations`, written in three places. Added 2026-08-03 after the
#: figure was found reading 451 in two of them and 452 in the third against a real 470 —
#: rotted by nineteen operations AND self-inconsistent, which is the state a number reaches
#: when nothing checks it. Same argument as the test count above; different denominator.
OPERATIONS_CLAIM = re.compile(r"all ([\d,]+) documented operations")


def _claimed() -> int:
    match = CLAIM.search(README.read_text())
    assert match, (
        "the README no longer states a test-count floor in the expected form "
        '("**N+ tests**"). Update this guard with the new wording.'
    )
    return int(match.group(1).replace(",", ""))


def _collected() -> int:
    """What pytest actually collects, from the same tree CI runs."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
         "--ignore=tests/rag_eval", "-p", "no:randomly"],
        cwd=BACKEND, capture_output=True, text=True, timeout=600,
    )
    match = re.search(r"(\d+) tests collected", result.stdout)
    if not match:
        pytest.skip(f"could not read a collection count from pytest:\n{result.stdout[-400:]}")
    return int(match.group(1))


class TestTheClaimIsReadable:
    def test_the_readme_states_a_floor(self):
        assert _claimed() > 0


class TestTheFloorIsTrue:
    def test_the_suite_is_at_least_as_big_as_claimed(self):
        claimed, actual = _claimed(), _collected()
        assert actual >= claimed, (
            f"the README claims {claimed:,}+ tests and pytest collects {actual:,}. The "
            "prose is now an overstatement — lower the figure, or find out which tests "
            "stopped being collected, because a drop of this kind is usually the second."
        )

    def test_the_floor_is_not_meaninglessly_low(self):
        """A floor far below reality passes forever and asserts nothing. This is the half
        that keeps the claim honest from the other direction, and the reason the original
        2,149 is not simply replaced with a comfortable 1,000."""
        claimed, actual = _claimed(), _collected()
        assert actual - claimed <= 600, (
            f"the README claims {claimed:,}+ while {actual:,} are collected — a "
            f"{actual - claimed:,}-test gap. Raise the figure: a floor nobody can fall "
            "through is not a claim about anything."
        )


def _documented_operations() -> int:
    """How many HTTP operations the OpenAPI schema actually declares.

    Read from the schema rather than from `app.routes`, because that attribute yields 2 of
    them — the routers are mounted, so the tree has to be walked. The contract gate drives
    this same schema, so this is the number the README is talking about.
    """
    from app.main import app

    spec = app.openapi()
    return sum(
        1
        for _path, item in spec["paths"].items()
        for method in item
        if method in ("get", "post", "put", "patch", "delete", "head", "options")
    )


class TestTheOperationCountIsNotStale:
    """The same rot, one table down.

    A test count changes several times a day, so it is claimed as a floor. An operation count
    changes when someone adds a router — rarely, and always deliberately — so it is claimed
    exactly, and an exact claim can be checked exactly.
    """

    def test_the_readme_states_the_operation_count(self):
        claims = OPERATIONS_CLAIM.findall(README.read_text())
        assert claims, (
            "no 'all N documented operations' claim found in the README; if the wording "
            "changed, update this pattern rather than deleting the guard"
        )

    def test_every_place_it_is_stated_agrees(self):
        """It was 451 in two places and 452 in a third. A reader cannot tell which is
        current, and both were wrong."""
        claims = {c.replace(",", "") for c in OPERATIONS_CLAIM.findall(README.read_text())}
        assert len(claims) == 1, (
            f"the README states the operation count as {sorted(claims)} in different places. "
            "One number, stated once per place, all agreeing."
        )

    def test_it_matches_the_schema(self):
        claimed = int(OPERATIONS_CLAIM.findall(README.read_text())[0].replace(",", ""))
        actual = _documented_operations()
        assert claimed == actual, (
            f"the README says the contract gate drives {claimed:,} documented operations; "
            f"the OpenAPI schema declares {actual:,}. This is the figure quoted to describe "
            f"how much of the API is covered, so it has to be the real one."
        )
