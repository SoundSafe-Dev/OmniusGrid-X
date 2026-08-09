"""The dock-production sync dashboard must account for every appointment.

THE DEFECT. `get_sync_dashboard` analyses each appointment inside a `try`, and on failure
it logged a warning and fell through — incrementing no bucket at all. The appointment
stayed in `total_appointments` but vanished from `sync_status_breakdown`, and worse, it
stayed in the denominator:

    sync_percent = (on_time + early) / total_appointments * 100

So **every failed analysis quietly pushed the reported sync percentage down**, making
dock-production performance look worse than it was, with nothing in the response saying
an analysis had failed. A number that moves for a reason the reader cannot see is worse
than no number.

Found by sweeping for handlers that swallow an exception and still report success — the
same class as the ERP `subscribe_to_events` that returned True for a subscription it
never created. This one is live: `get_sync_dashboard` has two callers, one of them an API
route.

Counting an unanalysable appointment as "not on time" would be a claim we cannot support:
we do not know its status, which is precisely the problem. It gets its own bucket and
leaves the denominator.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.services.logistics_correlation_engine import DockProductionSynchronizer


class _Appt:
    def __init__(self, operation_id=None):
        self.id = uuid.uuid4()
        self.operation_id = operation_id


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Session:
    """Returns a fixed appointment list and swallows the async-context protocol."""

    def __init__(self, appointments):
        self._appointments = appointments

    async def execute(self, *_args, **_kwargs):
        return _Result(self._appointments)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


async def _dashboard(appointments: List[_Appt], sync_results: Dict[Any, Any]) -> Dict[str, Any]:
    """Run the dashboard with `sync_dock_with_production` stubbed per appointment.

    A value of `Exception` for an appointment means its analysis raises.
    """
    synchronizer = DockProductionSynchronizer()

    async def _fake_sync(appointment_id, _session=None):
        outcome = sync_results[appointment_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with patch.object(synchronizer, "sync_dock_with_production", _fake_sync):
        return await synchronizer.get_sync_dashboard(
            organization_id=uuid.uuid4(),
            date=datetime.now(timezone.utc),
            db=_Session(appointments),
        )


class TestEveryAppointmentIsAccountedFor:
    async def test_a_failed_analysis_lands_in_a_bucket(self):
        """It used to increment nothing, so the breakdown silently omitted it."""
        ok, bad = _Appt("op-1"), _Appt("op-2")
        result = await _dashboard(
            [ok, bad],
            {ok.id: {"sync_status": "on_time"}, bad.id: RuntimeError("analysis blew up")},
        )
        assert result["sync_status_breakdown"]["analysis_failed"] == 1
        assert result["analysis_failed_count"] == 1

    async def test_the_buckets_sum_to_the_total(self):
        """The invariant the old code broke. If they do not sum, the breakdown is
        describing a different set of appointments than the headline count."""
        appts = [_Appt("op-1"), _Appt("op-2"), _Appt("op-3"), _Appt(None)]
        outcomes = {
            appts[0].id: {"sync_status": "on_time"},
            appts[1].id: {"sync_status": "late"},
            appts[2].id: RuntimeError("boom"),
        }
        result = await _dashboard(appts, outcomes)

        assert sum(result["sync_status_breakdown"].values()) == result["total_appointments"], (
            f"breakdown {result['sync_status_breakdown']} does not account for all "
            f"{result['total_appointments']} appointments"
        )

    async def test_an_unknown_status_still_lands_somewhere(self):
        """A status the dashboard does not recognise falls into no_operation rather
        than disappearing — the pre-existing behaviour, pinned so the sum invariant
        above cannot be satisfied by accident."""
        appt = _Appt("op-1")
        result = await _dashboard([appt], {appt.id: {"sync_status": "something_new"}})
        assert sum(result["sync_status_breakdown"].values()) == 1


class TestThePercentageIsNotDeflatedByFailures:
    async def test_a_failure_does_not_drag_the_percentage_down(self):
        """THE ASSERTION THIS FILE EXISTS FOR.

        One on-time appointment and one that could not be analysed is 100% of what we
        could assess — not 50%. Reporting 50% asserts the second one was not on time,
        which is exactly what we failed to determine.
        """
        ok, bad = _Appt("op-1"), _Appt("op-2")
        result = await _dashboard(
            [ok, bad],
            {ok.id: {"sync_status": "on_time"}, bad.id: RuntimeError("boom")},
        )
        assert result["production_dock_sync_percent"] == 100.0, (
            f"got {result['production_dock_sync_percent']}% — a failed analysis is "
            f"still inflating the denominator"
        )
        assert result["appointments_assessed"] == 1
        assert result["total_appointments"] == 2

    async def test_the_percentage_is_unchanged_when_nothing_fails(self):
        """The fix must not move the number on a clean run."""
        a, b = _Appt("op-1"), _Appt("op-2")
        result = await _dashboard(
            [a, b],
            {a.id: {"sync_status": "on_time"}, b.id: {"sync_status": "late"}},
        )
        assert result["production_dock_sync_percent"] == 50.0
        assert result["analysis_failed_count"] == 0
        assert result["appointments_assessed"] == 2

    async def test_all_analyses_failing_reports_zero_rather_than_dividing_by_zero(self):
        a, b = _Appt("op-1"), _Appt("op-2")
        result = await _dashboard(
            [a, b], {a.id: RuntimeError("x"), b.id: RuntimeError("y")}
        )
        assert result["production_dock_sync_percent"] == 0
        assert result["appointments_assessed"] == 0
        assert result["analysis_failed_count"] == 2

    async def test_unlinked_appointments_still_count_against_the_percentage(self):
        """An appointment with no operation is a REAL no_operation, not a measurement
        failure — we know its status. It stays in the denominator, unlike a failure."""
        linked, unlinked = _Appt("op-1"), _Appt(None)
        result = await _dashboard([linked, unlinked], {linked.id: {"sync_status": "on_time"}})
        assert result["appointments_assessed"] == 2
        assert result["production_dock_sync_percent"] == 50.0


class TestTheFailureIsVisibleToTheCaller:
    async def test_the_response_says_how_many_failed(self):
        """Without this a caller cannot distinguish a clean run from a partial one, and
        the percentage silently describes fewer rows than it appears to."""
        a, b = _Appt("op-1"), _Appt("op-2")
        result = await _dashboard(
            [a, b], {a.id: {"sync_status": "on_time"}, b.id: RuntimeError("boom")}
        )
        for key in ("analysis_failed_count", "appointments_assessed", "total_appointments"):
            assert key in result, f"{key} missing; the caller cannot see the shortfall"
        assert result["analysis_failed_count"] + result["appointments_assessed"] == result["total_appointments"]
