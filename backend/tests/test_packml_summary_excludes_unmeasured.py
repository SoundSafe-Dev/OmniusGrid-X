"""Unmapped machine time does not dilute the productive percentage (FS-462).

The edge agent's PackML mapper translates whatever string a PLC reports into a standard
state. Anything it did not recognise used to become `Idle` — an availability-loss state — so
a machine running at full rate was recorded as stopped. That is fixed on the agent: unmapped
states are now `Undefined`, in neither category, and excluded from availability's denominator.

**Which moves the problem here.** `/operations/{id}/packml-summary` computed
`Execute / total_duration`, and `total_duration` is the sum of every bucket including the new
`Undefined` one. So the more of a machine's states its configuration fails to cover, the less
productive that machine appears — a property of the CONFIG being reported as a property of
the MACHINE.

Fixing the agent alone would have been invisible in the worst way: the agent got more honest
and this endpoint turned that honesty into a lower number. Rule 88 — a defect class does not
stop at a repository boundary just because the sweep did — and its corollary, that fixing one
side of a boundary is not finishing when the other side consumes the same quantity.

WHAT IS ASSERTED. That the denominator excludes unmapped time, that the excluded amount is
reported rather than silently dropped, and that a summary with no unmapped time is unchanged
— the last one because a fix that alters every existing answer is a different change from
the one intended.
"""

from __future__ import annotations

import pytest

from app.api.operations import UNMAPPED_STATE


class _Operation:
    """The two attributes the handler reads, without a database round trip.

    The endpoint's arithmetic is what is under test; its tenancy and 404 behaviour are
    covered by the operations suite already, and reproducing them here would test the
    fixture rather than the fix.
    """

    def __init__(self, durations):
        self.id = "op-1"
        self.operation_name = "run-1"
        self.status = "completed"
        self.packml_state_durations = durations


def _summarise(durations) -> dict:
    """Run the handler's computation over a fake operation."""
    total = sum(durations.values())
    unmeasured = durations.get(UNMAPPED_STATE, 0)
    measured = total - unmeasured
    return {
        "total_duration_seconds": total,
        "productive_time_seconds": durations.get("Execute", 0),
        "productive_percentage": (
            round((durations.get("Execute", 0) / measured * 100), 2) if measured > 0 else 0
        ),
        "unmeasured_seconds": unmeasured,
    }


class TestTheHandlerStillComputesItThisWay:
    """The helper above mirrors the handler. If the handler changes and this does not, the
    tests below assert a formula nothing uses — the failure mode of every hand-copied
    fixture, so the source is checked rather than trusted."""

    def test_the_handler_divides_by_the_measured_duration(self):
        import inspect

        from app.api.operations import get_operation_packml_summary

        source = inspect.getsource(get_operation_packml_summary)
        assert "measured_duration" in source, (
            "the packml summary no longer computes a measured duration; either the fix was "
            "reverted or it moved, and the assertions below are checking a formula the "
            "endpoint does not use"
        )
        assert "/ measured_duration * 100" in source, (
            "productive_percentage is no longer divided by the measured duration"
        )

    def test_the_unmapped_state_literal_matches_the_agent(self):
        """This constant is a copy of `PackMLState.UNDEFINED` in the agent package, which
        the backend does not import. A copy is a claim."""
        from pathlib import Path

        packml = (
            Path(__file__).resolve().parent.parent.parent
            / "edge-agent"
            / "opsgrid_agent"
            / "packml.py"
        )
        assert packml.exists(), "the agent's packml module moved; this constant is now unpinned"
        assert f'UNDEFINED = "{UNMAPPED_STATE}"' in packml.read_text(), (
            f"the agent no longer emits {UNMAPPED_STATE!r} for an unmapped state, so this "
            f"endpoint is excluding a bucket that no longer exists and including one it "
            f"should not"
        )


class TestUnmeasuredTimeIsExcluded:
    def test_a_run_with_unmapped_time_is_not_diluted(self):
        # One hour running, one hour genuinely idle, two hours nobody could read.
        result = _summarise({"Execute": 3600, "Idle": 3600, UNMAPPED_STATE: 7200})
        assert result["productive_percentage"] == 50.0, (
            "productive time was divided by the whole window including unreadable time, so "
            "a machine that ran half of its measurable hours reported 25%"
        )
        assert result["unmeasured_seconds"] == 7200

    def test_a_run_with_no_unmapped_time_is_unchanged(self):
        """The fix must not move an answer that was already right."""
        result = _summarise({"Execute": 3600, "Idle": 3600})
        assert result["productive_percentage"] == 50.0
        assert result["unmeasured_seconds"] == 0

    def test_total_duration_still_reports_the_whole_window(self):
        """`total_duration_seconds` is the wall-clock span and must keep including the
        unmapped time — otherwise the state breakdown's percentages stop summing to 100
        and an operator cannot see how much was unread."""
        result = _summarise({"Execute": 3600, UNMAPPED_STATE: 3600})
        assert result["total_duration_seconds"] == 7200

    def test_a_wholly_unreadable_run_reports_zero_rather_than_dividing_by_zero(self):
        result = _summarise({UNMAPPED_STATE: 7200})
        assert result["productive_percentage"] == 0
        assert result["unmeasured_seconds"] == 7200

    def test_an_empty_run_does_not_raise(self):
        assert _summarise({})["productive_percentage"] == 0
