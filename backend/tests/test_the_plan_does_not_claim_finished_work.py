"""The sprint plan does not list work that is already done (FS-476).

Two plans in a row have overstated what remains. `fixed-sprints-241-343.md` was written from
the task pools, and five of the eight items examined described work already delivered.
`fixed-sprints-344-393.md` was written from the codebase specifically to avoid that — and by
2026-08-06 eight of ITS entries no longer reproduced either.

**Overstating is the harder direction to notice.** A plan that flatters gets checked, because
someone eventually looks for the thing it says is finished. A plan that inflates does not:
nobody investigates a backlog for being too long, and the cost is paid quietly, in work
planned twice and estimates built on a number that was never true.

WHAT THIS ASSERTS, AND WHY IT IS DELIBERATELY NARROW. Not that the plan is accurate — most
entries describe judgement calls and multi-day work no test can adjudicate. Only the one thing
that IS checkable: **an item the plan lists as outstanding must not name a defect the
repository has since closed by name.** When a later FS closes an earlier one, the later fix
says so, and this pairs the two.

The verification section is checked for staleness rather than the whole document, because
that section is the one making a dated claim about the present.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
PLAN = ROOT / "docs" / "planning" / "fixed-sprints-344-393.md"

#: Items the verification pass recorded as already delivered, each with the FS that closed
#: it where one exists. An entry here is a claim that the work is done, so it is checked.
DELIVERED: dict[str, str | None] = {
    "FS-266": None,      # org-scoped from the token
    "FS-272": None,      # the lane-failure allowlist is empty
    "FS-345": None,      # invented flag set where the position is fabricated
    "FS-350": None,      # gated on ALLOW_DEV_TOKEN
    "FS-354": None,      # both modules at zero get_db uses
    "FS-357": "FS-468",  # the doubled prefix
    "FS-359": None,      # has a test module
    "FS-361": None,      # has test modules
    "FS-355": None,      # the missing RLS policy is deliberate — see the redaction test
    "FS-360": None,      # four suites, 53 tests
    "FS-365": None,      # the e2e sweep walks 32 routes; the .visual.ts exclusion is on purpose
    # Wave F, verified closed 2026-08-06. The whole wave — "generated figures presented as
    # measurements" — was the highest-severity block in the plan and every item now has a
    # guard. Two of them are guarded without citing their FS number, so they are pinned to
    # the file carrying the argument instead, below.
    "FS-267": None,      # every gated geotab function stamps provenance
    "FS-344": None,      # the production validator refuses GEOTAB_SIMULATED
    "FS-346": None,      # the four uncomputed compliance figures are computed
    "FS-347": None,      # untagged rows are None, not silently excluded from the percentage
    "FS-348": None,      # the four route literals are settings, returned in `assumptions`
    "FS-349": None,      # model_version says "none (no correlation model loaded)"
    "FS-351": None,      # critical correlations reach the notification service
    "FS-352": None,      # the placeholder restart endpoint was removed, not stubbed
}

#: FS-355 is recorded as delivered on the strength of a decision written in a test
#: docstring, not a code change. That is a weaker kind of evidence, so it is pinned to the
#: document that carries the reasoning: if that test goes, the argument goes with it and the
#: entry needs re-opening rather than quietly staying closed.
_DECISION_EVIDENCE = {
    "FS-355": "test_error_triage_sample_redaction_realdb.py",
}

#: Items whose guard exists but does not cite the FS number, pinned to the file that holds it.
#:
#: Separate from `_DECISION_EVIDENCE` on purpose. That map is for a decision — a thing
#: deliberately NOT done, whose closure is an argument, so its test demands the file still
#: record what was rejected. These two are ordinary fixes with ordinary guards; the only
#: thing unusual about them is that the guard argues the subject instead of naming the item.
#: Filing them under "decision" would have made this register describe them wrongly, which
#: is how a register stops being read.
_GUARDED_WITHOUT_CITATION = {
    "FS-344": ("test_simulated_data_says_so.py", "GEOTAB_SIMULATED"),
    "FS-349": ("test_correlation_reporting_honesty.py", "gemma"),
}


def _plan() -> str:
    return PLAN.read_text()


class TestTheDocumentIsThere:
    def test_the_plan_exists(self):
        assert PLAN.exists(), f"{PLAN} is gone; this guard checks nothing"

    def test_the_verification_section_is_present(self):
        assert "## Verification pass, 2026-08-06" in _plan(), (
            "the dated verification section has been removed. It is the only part of this "
            "document making a claim about the present, and the only part this guard can "
            "hold to account."
        )


class TestTheDeliveredItemsAreStillDelivered:
    """Each entry in the table is a claim about code. Claims rot."""

    def test_the_table_lists_them_all(self):
        plan = _plan()
        section = plan.split("## Verification pass, 2026-08-06", 1)[1].split("### What is still open", 1)[0]
        missing = [fs for fs in DELIVERED if fs not in section]
        assert not missing, (
            f"{missing} are recorded here as delivered and are not in the plan's "
            f"verification table. The two have to agree or one of them is lying."
        )

    def test_the_table_lists_nothing_the_register_has_not_checked(self):
        """The direction the first version of this guard was missing.

        `test_the_table_lists_them_all` asserts register ⊆ table, so adding a row to the
        plan claiming something is done required nothing of anybody — the claim went in
        unchecked, which is precisely the failure this file exists to prevent, committed in
        the file that prevents it. Two rows (FS-360, FS-365) went in that way before this
        test was written.
        """
        plan = _plan()
        section = plan.split("## Verification pass, 2026-08-06", 1)[1].split("### What is still open", 1)[0]
        # A row whose first cell is not an FS number is a header or a separator.
        claimed = {row.split("|")[1].strip() for row in section.splitlines() if row.startswith("| FS-")}
        unchecked = sorted(claimed - set(DELIVERED))
        assert not unchecked, (
            f"the plan's verification table calls {unchecked} delivered and this register "
            f"does not check them, so the claim rests on nobody. Add each to DELIVERED with "
            f"the evidence, or take the row out of the table."
        )

    def test_the_lane_failure_allowlist_is_still_empty(self):
        """FS-272's evidence. If a 5xx is re-permitted the plan's claim stops being true."""
        source = (Path(__file__).resolve().parent / "_lane_failures.py").read_text()
        for name in ("GET_FAILURES", "WRITE_FAILURES"):
            match = re.search(rf"{name}[^=]*=\s*(\{{[^}}]*\}}|\{{\}})", source)
            assert match, f"{name} not found in _lane_failures.py"
            assert not match.group(1).strip("{} \n"), (
                f"{name} is no longer empty, so FS-272's residual 5xx work is open again "
                f"and the plan's verification table says otherwise"
            )

    @pytest.mark.parametrize(
        "fs,closer", [(k, v) for k, v in DELIVERED.items() if v is not None]
    )
    def test_the_closing_item_left_a_trace(self, fs: str, closer: str):
        """Where a later FS closed an earlier one, that fix should be findable — otherwise
        "closed by FS-468" is an assertion with nothing behind it."""
        found = False
        for root in (ROOT / "backend", ROOT / "edge-agent", ROOT / "frontend" / "src"):
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in {".py", ".ts", ".tsx"}:
                    try:
                        if closer in path.read_text():
                            found = True
                            break
                    except (UnicodeDecodeError, OSError):  # pragma: no cover
                        continue
            if found:
                break
        assert found, (
            f"the plan says {fs} was closed by {closer}, and {closer} appears nowhere in "
            f"the source. Either the fix was reverted or the citation is wrong."
        )


class TestTheStillOpenListIsHonest:
    """The other half. An item listed as open that has since been fixed is the same defect
    as an item listed as done that has not — it just fails in the flattering direction."""

    def test_it_names_items(self):
        plan = _plan()
        section = plan.split("### What is still open", 1)[1].split("\n---", 1)[0]
        assert re.findall(r"FS-\d+", section), "the still-open list names no items"

    def test_no_still_open_item_is_also_in_the_delivered_table(self):
        plan = _plan()
        still_open = plan.split("### What is still open", 1)[1].split("\n---", 1)[0]
        overlap = sorted(fs for fs in DELIVERED if re.search(rf"{fs}\b", still_open))
        assert not overlap, (
            f"{overlap} appear in both the delivered table and the still-open list. The "
            f"document contradicts itself, which is worse than either claim being wrong."
        )


class TestAGuardWithoutACitationIsStillFindable:
    """An entry closed by a guard that never names it is one rename from unverifiable."""

    @pytest.mark.parametrize(
        "fs,filename,subject",
        [(fs, f, sub) for fs, (f, sub) in sorted(_GUARDED_WITHOUT_CITATION.items())],
    )
    def test_the_guard_still_covers_its_subject(self, fs: str, filename: str, subject: str):
        path = Path(__file__).resolve().parent / filename
        assert path.exists(), (
            f"{fs} is recorded as closed by {filename}, and that file is gone. Nothing else "
            f"names {fs}, so the entry is unverifiable — reopen it or find the new guard."
        )
        assert subject.lower() in path.read_text().lower(), (
            f"{filename} no longer mentions {subject!r}, which is the subject {fs} was "
            f"closed on. The file survived and the coverage may not have."
        )


class TestDecisionsHaveTheirReasoningOnFile:
    """An entry closed by a DECISION rather than a change is closed by an argument.

    FS-355 says `error_events` has no RLS policy — true — and concludes a gap. The absence
    is deliberate: the table is a platform-wide triage view on purpose, the disclosure risk
    was reproduced and fixed by redaction, and the test below records why scoping the view
    by organisation was rejected.

    **Absence is not evidence of a gap until you have checked whether the absence is
    deliberate.** That reasoning lives in one docstring, and a docstring is easy to lose in
    a rewrite — so the entry's closure is pinned to it.
    """

    @pytest.mark.parametrize("fs,filename", sorted(_DECISION_EVIDENCE.items()))
    def test_the_reasoning_still_exists(self, fs: str, filename: str):
        path = Path(__file__).resolve().parent / filename
        assert path.exists(), (
            f"{fs} is recorded as closed because {filename} argues the design is "
            f"deliberate, and that file is gone. Without the argument the entry is open "
            f"again."
        )
        text = path.read_text()
        assert "rejected" in text.lower(), (
            f"{filename} no longer records what was rejected and why, which is the whole "
            f"of {fs}'s closure"
        )

