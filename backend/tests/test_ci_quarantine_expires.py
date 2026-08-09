"""CI excludes six tests. This is what stops that becoming permanent.

`ci-cd.yml` passes three `--ignore` and two `--deselect` flags to pytest. Every one is
justified — the ignored files fail at COLLECTION, so without the flags the whole backend job
dies before running anything — but a flag in a workflow file has no expiry, no owner and no
record of what would have to be true to remove it. It is a suppression, and this repository
has spent a long time learning what suppressions do: they convert a defect into a survivable
condition, and survivable conditions are never revisited.

WHAT THIS FILE ASSERTS.

  1. The quarantine list below and the flags in `ci-cd.yml` are the same set. Neither can
     drift, and — the direction that matters — **a new exclusion added to CI without a
     record here fails this test.**
  2. Each quarantined file still genuinely fails to collect. The moment one starts working,
     the quarantine is stale and its flag has to come out of CI; this test says so by
     failing.
  3. Each entry has an expiry, and the expiry has not passed. After it does, the test fails
     with the owner and the fix. That is the whole point: a suppression with no deadline is
     a decision nobody will make again.

WHY THE CODE IS NOT FIXED HERE. All three failures are import mismatches in the intake
lane's scenario builders — tests written against an API that never shipped. The renames look
trivial and are not mine to make: the assertions behind them are asserting behaviour that
lane is still building, and "fixing" the import would surface a body of failing expectations
I would then be tempted to edit. The exact mismatch is recorded against each entry instead,
so the owner's change is a two-minute one.
"""

from __future__ import annotations

import datetime
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "ci-cd.yml"
TESTS = pathlib.Path(__file__).resolve().parent


class Quarantined:
    def __init__(self, reason: str, owner: str, expires: str, fix: str):
        self.reason = reason
        self.owner = owner
        self.expires = datetime.date.fromisoformat(expires)
        self.fix = fix


#: Every test CI refuses to run, why, whose it is, and what would remove it.
#:
#: `expires` is a date by which someone has to either fix the test or write down a new
#: reason. It is deliberately not far away — the value of an expiry is that it arrives.
#: EMPTIED ON 2026-07-30. All three ignored files were rewritten against the API the
#: modules actually export and now collect and pass (8 + 6 + 7 tests), so their
#: --ignore flags came out of ci-cd.yml.
#:
#: The note at the top of this file said the renames were "not mine to make" because
#: the assertions might encode behaviour the lane was still building. Checking that
#: assumption is what dissolved it: the builders are not unbuilt, they are live on the
#: intake path — nlp_correlation.py:1594/1655/1794 and analysis_sessions.py:972 call
#: them — so the quarantine was hiding a gap in coverage of shipped code. The rewrites
#: assert each module's documented contract and change no production code.
IGNORED_FILES: dict[str, Quarantined] = {}

#: Individually deselected tests. Same contract, smaller blast radius.
#:
#: test_image_domain_mapper.py::test_map_image_domains was released on 2026-07-30 —
#: it was the same stale-API defect as the files above (it subscripted the mapping
#: object and passed its text under the wrong key), not the taxonomy disagreement
#: this entry guessed at.
#: EMPTY as of 2026-08-04 (FS-415) — see the note on REGISTER in test_quarantine.py.
#: CI now runs every test with no deselects.
DESELECTED: dict[str, Quarantined] = {}


def _workflow_text() -> str:
    return WORKFLOW.read_text()


class TestTheSweepIsNotVacuous:
    def test_the_workflow_is_readable(self):
        # If the path moves, every assertion below passes while checking nothing.
        assert WORKFLOW.exists(), f"{WORKFLOW} is gone; this guard is inspecting nothing"
        assert "pytest" in _workflow_text()

    def test_it_finds_the_exclusion_flags(self):
        """Each flag form must appear in the workflow while its register has entries.

        This asserted both forms unconditionally, which was right while the quarantine
        held five items and wrong the moment it held fewer: emptying IGNORED_FILES on
        2026-07-30 made a guard fail for the good outcome it exists to encourage. The
        condition is what the guard actually means — a register with entries and no
        matching flag in CI means the sweep below is inspecting nothing.
        """
        text = _workflow_text()
        if IGNORED_FILES:
            assert "--ignore=" in text, (
                f"{len(IGNORED_FILES)} file(s) are registered as quarantined but the "
                "workflow has no --ignore flag; the sweep is checking nothing"
            )
        if DESELECTED:
            assert "--deselect" in text, (
                f"{len(DESELECTED)} test(s) are registered as deselected but the "
                "workflow has no --deselect flag; the sweep is checking nothing"
            )


class TestTheListMatchesCi:
    def test_every_quarantined_file_is_excluded_in_ci(self):
        """The list is not a wish. If CI runs a file this claims is quarantined, the claim
        is false and the entry should go."""
        text = _workflow_text()
        missing = [name for name in IGNORED_FILES if f"--ignore=tests/{name}" not in text]
        assert not missing, (
            "these are recorded as quarantined but CI does not exclude them: "
            f"{missing}"
        )

    def test_ci_excludes_nothing_that_is_not_recorded(self):
        """THE DIRECTION THAT MATTERS. A new `--ignore` added to the workflow with no entry
        here fails this test — which is the only thing standing between "we skipped one
        broken file" and a workflow that quietly stops running half the suite."""
        found = set(re.findall(r"--ignore=tests/([\w.]+)", _workflow_text()))
        undocumented = sorted(found - set(IGNORED_FILES))
        assert not undocumented, (
            "CI excludes these and nothing explains why, who owns them, or what would "
            f"remove them: {undocumented}. Add an entry to IGNORED_FILES."
        )

    def test_every_deselected_test_is_recorded(self):
        found = set(re.findall(r"--deselect (\S+)", _workflow_text()))
        undocumented = sorted(found - set(DESELECTED))
        assert not undocumented, f"deselected in CI, unrecorded here: {undocumented}"


class TestTheQuarantineIsStillNecessary:
    @pytest.mark.parametrize("name", sorted(IGNORED_FILES))
    def test_the_file_still_fails_to_collect(self, name):
        """A quarantine that is no longer needed is worse than no quarantine: it hides a
        working test AND it makes the list untrustworthy. Collection is run in a subprocess
        because a broken import in this process would take this file down with it."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", f"tests/{name}"],
            cwd=REPO / "backend",
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            f"tests/{name} collects cleanly now — the quarantine is stale. Remove its "
            f"--ignore from ci-cd.yml and its entry from IGNORED_FILES.\n"
            f"Recorded reason was: {IGNORED_FILES[name].reason}"
        )


class TestTheDeselectionIsStillNecessary:
    @pytest.mark.parametrize("nodeid", sorted(DESELECTED))
    def test_the_test_still_fails(self, nodeid):
        """Same staleness question as the ignored files, one level finer. These fail on an
        ASSERTION rather than at collection, so they can be run directly — and a deselect
        that is no longer needed hides a working test while making the whole list look
        untrustworthy."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", nodeid],
            cwd=REPO / "backend",
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            f"{nodeid} passes now — the deselect is stale. Remove it from ci-cd.yml and "
            f"drop its entry.\nRecorded reason was: {DESELECTED[nodeid].reason}"
        )


class TestTheQuarantineExpires:
    @pytest.mark.parametrize("name", sorted(IGNORED_FILES) + sorted(DESELECTED))
    def test_the_expiry_has_not_passed(self, name):
        """The mechanism this file exists for. Every other assertion here keeps the record
        accurate; this one makes somebody act on it."""
        entry = IGNORED_FILES.get(name) or DESELECTED[name]
        today = datetime.date.today()
        assert today <= entry.expires, (
            f"the quarantine on {name} expired on {entry.expires}.\n"
            f"  owner: {entry.owner}\n"
            f"  reason: {entry.reason}\n"
            f"  fix: {entry.fix}\n"
            "Either do it, or move the date and say why in the entry — but do not delete "
            "this test."
        )

    def test_no_entry_is_quarantined_indefinitely(self):
        """A date far enough out is the same as no date. Two years is not an expiry."""
        horizon = datetime.date.today() + datetime.timedelta(days=365)
        too_far = {
            name: entry.expires
            for name, entry in {**IGNORED_FILES, **DESELECTED}.items()
            if entry.expires > horizon
        }
        assert not too_far, f"these expiries are more than a year out: {too_far}"

    def test_every_entry_says_who_and_how(self):
        """An expiry nobody owns expires onto nobody's desk."""
        for name, entry in {**IGNORED_FILES, **DESELECTED}.items():
            assert entry.owner, f"{name} has no owner"
            assert len(entry.reason) > 30, f"{name}'s reason is too thin to act on"
            assert len(entry.fix) > 20, f"{name} does not say what would fix it"
