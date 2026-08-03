"""The quarantine register — explicit, diagnosed, and EXPIRING (FS-237).

`ci-cd.yml` excluded three test files and deselected three tests behind a comment
saying "pre-existing, owned by the intake/parsing lane". That is how a temporary
exclusion becomes permanent: nothing recorded who owned it, why, what was actually
wrong, or when it should be revisited, so the exclusion outlived everyone's memory
of it and CI quietly stopped covering six things.

This register fixes the three failure modes of an informal quarantine:

1. NO DEADLINE. Each entry carries an ``expires`` date and this suite FAILS once it
   passes. The quarantine cannot outlive its welcome silently.
2. NO DIAGNOSIS. "Fails at collection" is not a diagnosis. Each entry records the
   actual cause, so the owner starts from a fact rather than a re-investigation.
3. NO STALENESS CHECK. An entry whose test now PASSES is worse than useless — CI is
   skipping working coverage. This suite runs each quarantined item and fails if it
   passes, which is exactly how ``test_normalize_key`` was found: deselected in CI
   while passing locally.

NOT A PLACE TO PARK YOUR OWN FAILURES. Adding an entry requires an owner, a real
diagnosis and a date, and the entry starts failing on that date. It is deliberately
more work than fixing most things.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Quarantined:
    target: str          # pytest node id or file path
    owner: str           # lane that owns the fix, not whoever noticed
    diagnosis: str       # the actual cause
    expires: date        # this suite fails from this date
    kind: str = "fails"  # "fails" (test runs, asserts wrong) or "collection"


# Everything CI currently skips. Expiry is 2026-09-23 — 60 days from when this
# register was written (2026-07-25), which is long enough to schedule and short
# enough that nobody inherits it silently.
_EXPIRY = date(2026, 9, 23)

#: FOUR ENTRIES WERE RELEASED ON 2026-07-30, by the staleness check below doing
#: exactly what it was built for. All four were the same defect — a test left
#: asserting an API the converged merge 42ed66d8 had replaced — and none of them
#: needed a production change:
#:
#:   tests/test_document_scenario_builder.py     rewritten, 8 tests
#:   tests/test_image_scenario_builder.py        rewritten, 6 tests
#:   tests/test_cross_file_scenario_builder.py   rewritten, 7 tests
#:   tests/test_image_domain_mapper.py::test_map_image_domains   one test repaired
#:
#: The register said these were "written against an API that never shipped" and
#: left them for the owning lane. That was half right: the API they wanted never
#: shipped, but the builders they cover are live — nlp_correlation.py and
#: analysis_sessions.py call them on every intake — so CI was skipping coverage
#: of production code, not of an unbuilt feature. The rewrites assert the
#: contract each module's own docstring states.
#: EMPTY as of 2026-08-04 (FS-415). The last entry — the domain mapper's table-content
#: branch — was the only one that ever needed a judgement rather than a rewrite, and the
#: register framed the choice correctly: "either table-content mapping has a gap, or the
#: expectation was never right."
#:
#: It was the gap. The keyword map contained no asset or failure word anywhere, and the
#: test had never passed since the day it was written alongside the mapper. The cost was not
#: the red test: `document_scenario_builder` does `if domain is None: continue`, so a table
#: keyed on asset_id produced no correlation scenario while the page still reported as
#: processed.
#:
#: An empty register is the goal, not a reason to delete this file. The guards below still
#: run, and the moment someone adds an entry they inherit an owner, a diagnosis and an expiry.
REGISTER: tuple[Quarantined, ...] = ()


def _run(target: str) -> subprocess.CompletedProcess:
    """Run one quarantined target in a SUBPROCESS.

    A nested in-process pytest run would inherit this session's plugins, fixtures
    and config, so a pass or fail here would not mean the same thing as it does in
    CI. A subprocess gives the same answer CI gets.
    """
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", target],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )


class TestQuarantineHasNotExpired:
    @pytest.mark.parametrize("entry", REGISTER, ids=lambda e: e.target)
    def test_entry_is_still_within_its_window(self, entry: Quarantined):
        today = date.today()
        assert today < entry.expires, (
            f"QUARANTINE EXPIRED for {entry.target}\n"
            f"  owner:     {entry.owner}\n"
            f"  diagnosis: {entry.diagnosis}\n"
            f"  expired:   {entry.expires} (today is {today})\n\n"
            f"Fix it, or make a deliberate decision to extend the window and say "
            f"why. Extending by editing the date without a reason is how the "
            f"informal quarantine this register replaced came about."
        )


class TestQuarantineIsNotStale:
    """Fails when a quarantined item starts passing — CI is skipping live coverage.

    This is the half that earns the register its keep. `test_normalize_key` was on
    the CI deselect list and passing locally, so the pipeline was skipping a working
    test with nobody aware.
    """

    @pytest.mark.parametrize("entry", REGISTER, ids=lambda e: e.target)
    def test_entry_still_fails(self, entry: Quarantined):
        result = _run(entry.target)
        assert result.returncode != 0, (
            f"{entry.target} now PASSES and should be removed from the quarantine.\n"
            f"  owner:     {entry.owner}\n"
            f"  diagnosis: {entry.diagnosis}\n\n"
            f"Remove it from REGISTER here AND from the --ignore/--deselect list in "
            f".github/workflows/ci-cd.yml, so CI covers it again. Leaving it means "
            f"the pipeline is skipping a test that works."
        )


class TestRegisterMatchesCI:
    """The register and the CI exclusions must not drift apart.

    A register that lists things CI still runs, or misses things CI skips, is
    documentation rather than enforcement.
    """

    def test_every_ci_exclusion_is_registered(self):
        workflow = (BACKEND.parent / ".github" / "workflows" / "ci-cd.yml").read_text()

        excluded: set[str] = set()
        for line in workflow.splitlines():
            line = line.strip().rstrip("\\").strip()
            for flag in ("--ignore=", "--deselect "):
                if line.startswith(flag):
                    excluded.add(line[len(flag):].strip())

        registered = {e.target for e in REGISTER}
        unregistered = excluded - registered
        assert not unregistered, (
            "CI excludes these without a quarantine entry, so they have no owner, "
            f"no diagnosis and no expiry: {sorted(unregistered)}"
        )

        # And the other direction: an entry CI no longer excludes is dead weight.
        stale = registered - excluded
        assert not stale, (
            f"These are registered but CI no longer excludes them: {sorted(stale)}"
        )
