"""Fan-out reports what actually happened, per target (FS-655).

326 lines with **four production importers and no test naming the module**. The router that
calls it turns its result into what an operator is told, so a summary that overstates is a
shop-floor instruction nobody carries out.

WHY `FanoutResult.summary()` IS THE THING TO PIN. A shop-floor event goes to several systems
of record, and they do not all succeed. The dangerous default is "it went everywhere": a
caller that sees a 200 and a list of targets reads success, and the part never gets issued
because one target needed a person and said so quietly. `fully_posted` and
`awaiting_a_person` exist so that reading is impossible — this file keeps them honest.

The fan-out itself writes through a session; these are the pure decisions around it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.shop_floor_fanout import FanoutResult


@dataclass
class _Posting:
    """The two fields `summary()` reads. A real `SystemOfRecordPosting` is an ORM row and
    needs a session; the summary only ever looks at status, target and instruction."""

    status: str
    target_system: str = "sap"
    instruction: str | None = None


def _result(*statuses: str) -> FanoutResult:
    return FanoutResult(
        event_type="part_issue",
        event_id="evt-1",
        postings=[_Posting(status=s, target_system=f"sys-{i}") for i, s in enumerate(statuses)],
    )


class TestFullyPostedMeansEveryTarget:
    def test_all_posted_is_fully_posted(self):
        assert _result("posted", "posted").summary()["fully_posted"] is True

    def test_one_failure_is_not_fully_posted(self):
        """The assertion the whole class exists for. Three of four succeeding is not
        success — the fourth system is the one holding the part."""
        assert _result("posted", "posted", "failed").summary()["fully_posted"] is False

    def test_one_manual_target_is_not_fully_posted(self):
        """`manual_required` is not a failure and it is not a success: somebody has to do
        something. Counting it as posted is how an instruction gets lost."""
        assert _result("posted", "manual_required").summary()["fully_posted"] is False

    def test_no_targets_at_all_is_not_reported_as_success(self):
        """`all([])` is True, so an event that reached NOTHING would report
        `fully_posted: True` — a verdict computed from emptiness, on the path where the
        verdict means "the part was issued"."""
        summary = _result().summary()
        assert summary["targets"] == 0
        assert summary["fully_posted"] is not True, (
            "an event with no targets reported as fully posted: the operator is told the "
            "work went through when it went nowhere"
        )


class TestTheManualWorkIsNamed:
    def test_a_manual_posting_is_listed_for_a_person(self):
        result = FanoutResult(
            event_type="part_issue",
            event_id="evt-2",
            postings=[
                _Posting(status="posted", target_system="sap"),
                _Posting(
                    status="manual_required",
                    target_system="legacy-mrp",
                    instruction="Issue 4 EA of part 88-2 to WO-91",
                ),
            ],
        )
        summary = result.summary()
        assert summary["awaiting_a_person"] == [
            {"target": "legacy-mrp", "instruction": "Issue 4 EA of part 88-2 to WO-91"}
        ]

    def test_the_instruction_travels_with_the_target(self):
        """A list of instructions without their systems tells a clerk what to do and not
        where — which is the one question they cannot answer themselves."""
        result = _result("manual_required")
        entry = result.summary()["awaiting_a_person"][0]
        assert set(entry) == {"target", "instruction"}

    def test_nothing_awaits_a_person_when_everything_posted(self):
        """The positive control: if this listed something for every event, an operator
        would learn to ignore it."""
        assert _result("posted", "posted").summary()["awaiting_a_person"] == []


class TestTheCountsArePerStatus:
    def test_each_status_is_counted_separately(self):
        counts = _result("posted", "posted", "failed", "manual_required").summary()["by_status"]
        assert counts == {"posted": 2, "failed": 1, "manual_required": 1}

    @pytest.mark.parametrize("status", ["posted", "failed", "manual_required"])
    def test_by_status_selects_only_that_status(self, status):
        assert all(p.status == status for p in _result("posted", "failed", "manual_required").by_status(status))
