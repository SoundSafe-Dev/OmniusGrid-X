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
import importlib.util
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


def _floors() -> tuple[int, int]:
    r"""Import the floors rather than grep for them.

    This test USED to read `^BASELINE_PASSING = (\d+)` out of the file, and FS-654 turned that
    line into `BASELINE_PASSING = BASELINE_WITHOUT_BROKER` — a regex over source cannot follow
    an indirection, and it would have failed with "BASELINE_PASSING is gone" while the constant
    was sitting right there. The same mistake once counted a live module as dead by grepping
    for its name in the file that already listed it as a positive control.
    """
    spec = importlib.util.spec_from_file_location("contract_ratchet", RATCHET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BASELINE_WITHOUT_BROKER, module.BASELINE_WITH_BROKER


class TestTheNumbersInTheDocAndTheRatchetAgree:
    def test_the_floor_the_doc_cites_is_the_floor_in_force(self):
        """A document quoting a floor the script does not hold is how a reader concludes a
        regression is acceptable, or that headroom exists which does not."""
        without, _ = _floors()
        assert f"floor was re-baselined to {without}" in DOC.read_text(), (
            f"the document does not name the floor actually in force ({without}). The one it "
            f"names is what somebody will plan against."
        )

    def test_the_broker_floor_is_never_the_lower_one(self):
        """FS-654 split one floor into two, and the whole design rests on which is which. A
        transposition would hold a broker-less run to the broker floor — failing every build
        in which the broker did not come up, which is exactly how this job's predecessor
        became advisory and got killed.

        WAS `with_broker > without`, RELAXED TO `>=` ON MEASUREMENT (FS-738). The strict
        form encoded a premise — a reachable broker turns correct 503s into 2xx, so it must
        reach more conforming operations — that four runs no longer support:

            no broker   456, 458      (5xx: 33, 31)
            broker      454, 457      (5xx: 35, 32)

        The ranges overlap and the broker side is, if anything, marginally worse; every
        non-`ServerError` check is IDENTICAL across all four runs (33 / 22 / 2 / 1), which
        is what says the difference is the known flapping set rather than a real effect.
        The gap the split was built on has closed — the ratchet file predicted this in as
        many words ("very little of it now blocks on the broker") — so the two floors are
        now equal, and equal must be allowed.

        The invariant that still matters is the one this test is named for: the broker
        floor may never be the LOWER of the two, because that is the transposition that
        fails every broker-less build. `>=` keeps that and stops demanding a difference
        the measurement does not show."""
        without, with_broker = _floors()
        assert with_broker >= without, (
            f"BASELINE_WITH_BROKER ({with_broker}) is BELOW BASELINE_WITHOUT_BROKER "
            f"({without}). A run that reaches at least as many operations because a "
            f"dependency was present cannot be held to a lower bar than one that could not "
            f"reach them."
        )

    def test_neither_floor_has_been_lowered(self):
        """The one rule this whole gate has: a floor may rise and may never fall. Recorded as
        literals because the point is to fail when the constants change, not to restate them.
        Raising a floor means editing this line too, deliberately, in the same commit."""
        without, with_broker = _floors()
        assert without >= 380, (
            f"BASELINE_WITHOUT_BROKER is {without}, below the 380 measured 2026-08-07. A "
            f"lowered ratchet is indistinguishable from no ratchet."
        )
        assert with_broker >= 393, (
            f"BASELINE_WITH_BROKER is {with_broker}, below the 393 set from the 402 measured "
            f"2026-08-08 less its 9-operation spread."
        )

    def test_the_probe_decides_the_floor_rather_than_a_flag(self):
        """A flag is a claim, and the lower floor is the one somebody would want on a red
        build. `--broker` names an address to PROBE; it cannot assert a broker was present."""
        source = RATCHET.read_text()
        assert "def broker_is_reachable" in source, (
            "the broker probe is gone. Without it the two floors are selected by assertion, "
            "and 'the broker must have been down' is unfalsifiable after the fact."
        )
        assert "socket.create_connection" in source, (
            "the probe no longer opens a connection, so it is no longer a measurement"
        )

    def test_the_doc_records_the_cost_of_the_restricted_role(self):
        """The five-operation drop is the argument for the re-baseline. Without it, 380
        beside a previously-cited 392 reads as a floor somebody lowered."""
        assert "397" in DOC.read_text() and "392" in DOC.read_text(), (
            "the before/after measurement is gone from the document, so the re-baseline "
            "reads as a lowered floor rather than a measured one"
        )
