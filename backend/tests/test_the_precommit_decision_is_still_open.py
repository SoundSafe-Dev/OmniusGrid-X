"""The `pre-commit` decision has not been made quietly (FS-574).

`quality-gates.yml` runs the formatting hooks with `continue-on-error: true`, above a comment
reading *"Advisory while the existing tree is brought into compliance."* The tree has not been
brought into compliance, and the comment has been true long enough that it now describes a
decision rather than a transition. `docs/engineering/open-decisions.md` carries the entry.

WHAT THIS PINS, AND WHY AN OPEN DECISION NEEDS A PIN AT ALL. Not that the decision is right —
both answers are defensible, and the register says so. Only that the situation it describes is
still the situation. Two ways it could stop being true without anyone updating the page:

  * somebody deletes `continue-on-error`, and the entry then describes an advisory job that is
    now blocking every build;
  * somebody drops the formatting hooks, and the entry describes a reformat that would no
    longer happen.

Both are one-line edits made for good local reasons, and neither would fail anything today. A
register whose entries can go stale silently is the thing this repository keeps rediscovering.

WHAT IS NOT ASSERTED: the 972-file diff. Reproducing it needs the hook versions pinned in
`.pre-commit-config.yaml`, and a count computed with a locally-installed `ruff` would be a
different number presented as the same one — the binary on this machine reports 570 Python
files where the pinned v0.6.9 may not agree. A dated measurement with the command beside it is
honest. A live one computed the wrong way is not, and it would add a whole-tree format run to
every test session in order to be wrong.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gates.yml"
CONFIG = ROOT / ".pre-commit-config.yaml"
REGISTER = ROOT / "docs" / "engineering" / "open-decisions.md"

#: The hooks that would rewrite existing files. `check-yaml`, `check-merge-conflict`,
#: `check-added-large-files` and `gitleaks` are excluded on purpose: they pass on this tree
#: today, so they are not what the decision is about — making the job blocking costs nothing
#: for them, and it is only the formatters that carry the 972 files.
FORMATTING_HOOKS = ("trailing-whitespace", "end-of-file-fixer", "ruff-format", "prettier")


def _job() -> str:
    """The `pre-commit:` job block, up to the next job at the same indent."""
    text = WORKFLOW.read_text()
    start = text.index("\n  pre-commit:\n")
    rest = text[start + 1 :]
    following = re.search(r"\n  [a-z][\w-]*:\n", rest)
    return rest[: following.start()] if following else rest


class TestTheMeasurementIsReal:
    def test_the_workflow_still_runs_the_hooks(self):
        """Vacuity. If the job were renamed, `_job()` would raise rather than return a slice
        of some neighbouring job — but only because this asserts what the slice contains.

        ASKS FOR THE HOOKS, NOT FOR ONE MECHANISM (FS-767). This required
        `uses: pre-commit/action`, and failed the day the job switched to running
        `pre-commit run --files` directly — a change made because `--all-files` demanded a
        1,159-file reformat and had therefore failed on every run since it was added. The
        register's entry was still true; the guard was pinned to the implementation rather
        than to the fact it exists to protect.
        """
        job = _job()
        assert "pre-commit" in job and ("pre-commit run" in job or "pre-commit/action" in job), (
            "the pre-commit job no longer runs the hooks at all, so the register's entry is "
            "about a job that has changed shape"
        )

    def test_the_formatters_are_still_the_open_question(self):
        """The register's whole subject is the tree-wide reformat. If the formatters were
        quietly dropped from the config — or silently un-SKIPped and the tree reformatted —
        the entry would describe a decision nobody has to make any more."""
        config = CONFIG.read_text()
        for hook in ("ruff-format", "prettier"):
            assert hook in config, f"{hook} left .pre-commit-config.yaml; the entry is stale"

    def test_the_slice_stops_at_the_next_job(self):
        """A slice that ran to the end of the file would find `continue-on-error` belonging
        to some other job and report this one advisory when it is not."""
        assert "supply-chain:" not in _job()


class TestTheDecisionIsStillOpen:
    def test_the_job_is_still_advisory(self):
        assert "continue-on-error: true" in _job(), (
            "the pre-commit job is no longer advisory. Either the tree-wide reformat has "
            "happened or every build is now failing on formatting — either way the decision "
            "was made, so close the entry in docs/engineering/open-decisions.md rather than "
            "leaving a register that describes a choice somebody already took."
        )

    @pytest.mark.parametrize("hook", FORMATTING_HOOKS)
    def test_the_hook_that_would_rewrite_the_tree_is_still_declared(self, hook: str):
        assert f"id: {hook}" in CONFIG.read_text(), (
            f"`{hook}` is gone from .pre-commit-config.yaml, so the reformat the register "
            f"describes is smaller than the figure it states. Re-measure and update it."
        )


class TestTheRegisterStillCarriesIt:
    """The entry and this guard are a pair, and a pair needs something reading both."""

    def test_the_entry_exists(self):
        assert "pre-commit` is advisory" in REGISTER.read_text(), (
            "the open-decisions register no longer carries the pre-commit entry. If the "
            "decision was made, delete this file with it — a guard pinning an entry that is "
            "gone asserts a situation nobody is deciding about."
        )

    def test_the_entry_names_this_file(self):
        assert "test_the_precommit_decision_is_still_open.py" in REGISTER.read_text()
