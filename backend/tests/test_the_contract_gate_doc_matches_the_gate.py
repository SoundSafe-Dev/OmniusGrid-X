"""What the contract-gate document says the gate does, the gate does (FS-573).

`docs/engineering/api-contract-gate.md` carried a section headed *"Known limitation: this
gate runs with RLS inert"*, ending **"This gate does not do the same yet."** FS-307 had
already fixed it: the job provisions `omniusgrid_contract` with `provision_app_role.py` and
connects as that role, and the ratchet's own comments record the five-operation cost of the
change. The document went on describing the old state for two weeks.

WHY THAT PARTICULAR STALENESS IS EXPENSIVE. A *closed* limitation that still reads as open is
worse than an unrecorded one. Somebody planning work reads it and either re-does the fix, or
discounts the gate's results on a caveat that no longer applies — and this document exists
precisely to be read before touching a blocking gate. It is also the shape the repository
keeps finding: the fix commit updated the code, the ratchet and the workflow, and left the
prose that motivated all three.

WHAT THIS PAIRS. Not the whole document — most of it is analysis no test can adjudicate. Only
the handful of claims that are checkable against the workflow and the ratchet beside it, and
each in the direction that has already gone wrong once: the doc must not describe a
configuration the gate no longer has.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "engineering" / "api-contract-gate.md"
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gates.yml"
RATCHET = ROOT / "backend" / "scripts" / "contract_ratchet.py"


def _contract_job() -> str:
    text = WORKFLOW.read_text()
    start = text.index("\n  api-contract:\n")
    rest = text[start + 1 :]
    following = re.search(r"\n  [a-z][\w-]*:\n", rest)
    return rest[: following.start()] if following else rest


class TestTheSliceIsReal:
    def test_the_job_exists(self):
        """Vacuity. Every assertion below reads this slice, so a rename must fail here
        rather than silently make the slice something else."""
        job = _contract_job()
        assert "test_api_contract.py" in job
        assert "backend-realdb:" not in job, "the slice ran past the end of the job"


class TestTheDocDoesNotDescribeAGateThatIsGone:
    def test_it_does_not_still_claim_the_gate_is_a_superuser(self):
        """The exact sentence that was wrong. Asserted as a phrase rather than a section
        heading because the heading was rewritten and the sentence beneath it was what a
        reader would have acted on."""
        assert "This gate does not do the same yet." not in DOC.read_text(), (
            "the document still says the contract gate has no restricted role. FS-307 gave "
            "it one — the job runs provision_app_role.py and connects as "
            "omniusgrid_contract — so this reads as an open limitation that was closed, "
            "which is more expensive than an unrecorded one: it gets planned again, or it "
            "gets used to discount the gate's results."
        )

    def test_the_gate_really_does_provision_the_restricted_role(self):
        """The other half of the pair. Without this, deleting the role from the workflow
        would make the assertion above pass while the document became wrong again — in the
        opposite direction, and with nothing to notice it."""
        job = _contract_job()
        assert "provision_app_role.py" in job, (
            "the contract job no longer provisions a restricted role, so it is back to "
            "exercising the API with tenant isolation switched off — and the document now "
            "says that limitation is closed"
        )
        assert "omniusgrid_contract:" in job, (
            "the job provisions the restricted role and does not connect as it, which is "
            "the worst of both: the setup cost with none of the coverage"
        )


class TestTheNumbersInTheDocAndTheRatchetAgree:
    def test_the_floor_the_doc_cites_is_the_floor_in_force(self):
        """A document quoting a floor the script does not hold is how a reader concludes a
        regression is acceptable, or that headroom exists which does not."""
        match = re.search(r"^BASELINE_PASSING = (\d+)", RATCHET.read_text(), re.M)
        assert match, "BASELINE_PASSING is gone from contract_ratchet.py"
        floor = int(match.group(1))
        assert f"floor was re-baselined to {floor}" in DOC.read_text(), (
            f"the document does not name the floor actually in force ({floor}). The one it "
            f"names is what somebody will plan against."
        )

    def test_the_doc_records_the_cost_of_the_restricted_role(self):
        """The five-operation drop is the argument for the re-baseline. Without it, 380
        beside a previously-cited 392 reads as a floor somebody lowered."""
        assert "397" in DOC.read_text() and "392" in DOC.read_text(), (
            "the before/after measurement is gone from the document, so the re-baseline "
            "reads as a lowered floor rather than a measured one"
        )
