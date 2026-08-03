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

#: `**3,100+ tests**` in the CI-safety table.
CLAIM = re.compile(r"\*\*([\d,]+)\+ tests\*\*")


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
