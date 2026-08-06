"""A trailer with no recorded check-in has an unknown dwell, not a zero one (FS-465).

Found by the third leg of the carry-across pass — the classes closed in the backend and the
edge agent, re-asked of the frontend. The frontend sweep for "absence coerced into a number"
landed on `(r.dwellHours ?? 0) * 60`, and following it back found the two producers.

**Two code paths computed the same quantity and disagreed about the same input.**

    _calculate_dwell_hours    end_time - _as_utc(None)   -> TypeError, i.e. a 500
    the dwell-times query     ... if check_in else 0.0   -> 0.0, i.e. "arrived just now"

One crashed and one lied, and the lie is the worse of the two: the yard page's banner exists
to say how many trailers have been sitting past a 120-minute target, and a trailer nobody can
age was silently scored as the most favourable possible value. It was then averaged in at zero
by the client, pulling the mean down, while being excluded from the count the banner reports.

`check_in_at` IS NULLABLE. Its `default=utcnow` is applied by the ORM and skipped by a raw
insert — a case this repository already tests for, since `test_raw_insert_timestamps.py`
parametrises over `yard_trailers` specifically.

THE COMMENT ON THE NEXT LINE ALREADY KNEW. Immediately below the `else 0.0`, the source
explains at length that `detention_charge` must stay null until a charge is assessed, because
"`float(None or 0)` turns 'not yet worked out' into 'nothing owed'". Someone reasoned
carefully about exactly this class, one line down, and the sibling expression above it went
untouched. That is worth recording: proximity to a correct decision is not protection.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from app.services.yard_management import YardManagementService, _as_utc


class _Trailer:
    """Only the two attributes the calculator reads."""

    def __init__(self, check_in_at, check_out_at=None):
        self.check_in_at = check_in_at
        self.check_out_at = check_out_at


@pytest.fixture
def service() -> YardManagementService:
    return YardManagementService()


class TestTheCalculatorHandlesAMissingCheckIn:
    def test_it_returns_none_rather_than_raising(self, service):
        assert service._calculate_dwell_hours(_Trailer(None)) is None, (
            "a trailer with no check-in must yield an unknown dwell; this used to raise "
            "TypeError and 500 the yard inventory"
        )

    def test_it_returns_none_rather_than_zero(self, service):
        """The distinction the whole fix rests on. Zero is the most favourable reading
        available on a page built to report trailers that have been sitting too long."""
        assert service._calculate_dwell_hours(_Trailer(None)) != 0.0

    def test_a_real_check_in_still_computes(self, service):
        """The other direction: returning None unconditionally passes both tests above."""
        check_in = datetime.now(timezone.utc) - timedelta(hours=3)
        assert service._calculate_dwell_hours(_Trailer(check_in)) == pytest.approx(3.0, abs=0.05)

    def test_a_checked_out_trailer_measures_to_its_departure(self, service):
        check_in = datetime.now(timezone.utc) - timedelta(hours=10)
        check_out = check_in + timedelta(hours=2)
        assert service._calculate_dwell_hours(_Trailer(check_in, check_out)) == pytest.approx(2.0)

    def test_a_genuinely_zero_dwell_is_still_zero(self, service):
        """A trailer that checked in and out at the same instant really did dwell zero
        hours. Blanking that would trade one wrong answer for another."""
        now = datetime.now(timezone.utc)
        assert service._calculate_dwell_hours(_Trailer(now, now)) == 0.0

    def test_a_naive_timestamp_does_not_reintroduce_the_crash(self, service):
        """`_as_utc` exists because mixing naive and aware raises. The None guard must sit
        AFTER the coercion, or a naive check-in takes a different path than an aware one."""
        # NAIVE **UTC**, which is what `_as_utc` documents it assumes. The first draft of
        # this test used `datetime.now()` — naive LOCAL — and got 6.0 hours instead of 1.0
        # on a host at -05:00. That is FS-461's class landing in a test written to check a
        # different one, and it is the same trap: a bare `datetime.now()` looks correct
        # and is wrong by the host's offset.
        naive_utc = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        assert service._calculate_dwell_hours(_Trailer(naive_utc)) == pytest.approx(
            1.0, abs=0.05
        )


class TestTheOtherProducerAgrees:
    """The dwell-times query computes the same quantity in its own expression. Two
    producers of one number is how this defect existed in two different forms."""

    def test_the_query_path_yields_none_for_a_missing_check_in(self):
        source = inspect.getsource(YardManagementService)
        assert "if check_in else None" in source, (
            "the dwell-times query no longer returns None for a trailer without a "
            "check-in. If it is back to `else 0.0`, a trailer nobody can age is once "
            "again reported as having just arrived"
        )

    def test_neither_path_returns_a_bare_zero_for_absence(self):
        source = inspect.getsource(YardManagementService)
        assert "if check_in else 0.0" not in source, (
            "`else 0.0` is back in a dwell calculation"
        )


class TestTheSchemaAdmitsTheAbsence:
    def test_dwell_hours_is_optional_on_the_wire(self):
        """A `float` field cannot carry "unknown", so the fix cannot reach a caller
        without this — and FastAPI would raise on serialising None against `float`."""
        from app.models.schemas import DwellTimeAnalytics

        field = DwellTimeAnalytics.model_fields["dwell_hours"]
        assert not field.is_required() or field.annotation is not float, (
            "dwell_hours is still a required float, so a None from the service cannot be "
            "serialised and the endpoint would 500 on exactly the trailer this fixes"
        )
        assert "Optional" in str(field.annotation) or "None" in str(field.annotation), (
            f"dwell_hours is annotated {field.annotation}, which cannot represent an "
            f"unmeasured dwell"
        )
