"""What a carrier gets billed, and nothing had ever checked it (FS-360, FS-391).

`app/services/yard_management.py` is 749 lines behind a live API surface and had **zero
tests**. Four yard test files exist and none of them import it: `test_yard_detention.py`
tests `build_detention_alert` in `app/api/yard.py` — a different function, in a different
module, that happens to share a subject.

`DetentionCalculator` is the part worth starting with, because its output is money.
`_finalize_wait_time` writes `detention_charge` and `demurrage_charge` onto the
`driver_wait_times` row when a trailer checks out, and that is what a carrier is invoiced.

THE DEFECT FOUND WHILE WRITING THESE. Both calculators compared a stored timestamp
against `datetime.now(timezone.utc)`, and a naive input raised:

    TypeError: can't subtract offset-naive and offset-aware datetimes

`DriverWaitTime.check_in_at` is `DateTime(timezone=True)`, so Postgres returns an aware
value and production is fine. SQLite cannot preserve tzinfo, so on the documented local
dev path (`make demo` against dev.db) every one of these is naive and checking out a
trailer raised out of `_finalize_wait_time` before any charge was computed. Reproduced
directly against the real function, not deduced from the column type.

WHY THE BOUNDARY CASES MATTER MORE THAN THE HAPPY PATH HERE. Every one of them is a
number somebody pays or does not pay:

  * exactly at the free-time limit — bill or not
  * a clock skew that puts check-out before check-in — a negative charge is worse than none
  * `unloaded_at` absent — a trailer still on site accrues nothing, which is a policy
    choice this file pins so a later change to it is deliberate rather than incidental
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.yard_management import DetentionCalculator

RATE = 60.0          # $/hour, chosen so a minute is exactly $1
FREE = 120           # minutes


def at(minutes: float, *, aware: bool = True) -> datetime:
    """A timestamp `minutes` after a fixed origin."""
    base = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc if aware else None)
    return base + timedelta(minutes=minutes)


class TestDetentionIsOnlyChargedPastTheFreeWindow:
    def test_inside_free_time_is_free(self):
        result = DetentionCalculator.calculate_detention(
            check_in_at=at(0), unloaded_at=at(30), check_out_at=at(60),
            hourly_rate=RATE, free_minutes=FREE,
        )
        assert result["is_detention"] is False
        assert result["detention_charge"] == 0.0

    def test_exactly_at_the_limit_is_free(self):
        """The boundary is `<=`, so 120 minutes of a 120-minute allowance bills nothing.
        Pinned because it is the single most arguable number in the function and a `<`
        would move it silently."""
        result = DetentionCalculator.calculate_detention(
            check_in_at=at(0), unloaded_at=at(30), check_out_at=at(FREE),
            hourly_rate=RATE, free_minutes=FREE,
        )
        assert result["is_detention"] is False

    def test_one_minute_past_the_limit_bills_one_minute(self):
        result = DetentionCalculator.calculate_detention(
            check_in_at=at(0), unloaded_at=at(30), check_out_at=at(FREE + 1),
            hourly_rate=RATE, free_minutes=FREE,
        )
        assert result["is_detention"] is True
        assert result["detention_minutes"] == 1
        assert result["detention_charge"] == 1.0  # $60/h == $1/min

    def test_only_the_excess_is_billed_not_the_whole_stay(self):
        """The free window is a deduction, not a threshold. Billing all 180 minutes once
        the limit is passed would triple every invoice."""
        result = DetentionCalculator.calculate_detention(
            check_in_at=at(0), unloaded_at=at(30), check_out_at=at(180),
            hourly_rate=RATE, free_minutes=FREE,
        )
        assert result["detention_minutes"] == 60
        assert result["detention_charge"] == 60.0

    def test_the_rate_is_the_one_passed(self):
        """`_finalize_wait_time` passes `wait_time.detention_rate` — the carrier's
        contracted rate — and falls back to the default only when the row has none. A
        calculator that ignored the argument would bill every carrier the same."""
        result = DetentionCalculator.calculate_detention(
            check_in_at=at(0), unloaded_at=at(30), check_out_at=at(180),
            hourly_rate=120.0, free_minutes=FREE,
        )
        assert result["detention_charge"] == 120.0
        assert result["hourly_rate"] == 120.0


class TestTheCasesThatWouldProduceAWrongInvoice:
    def test_a_trailer_that_never_unloaded_is_not_charged(self):
        """A POLICY, pinned so changing it is deliberate. Detention here is gated on
        `unloaded_at`: a trailer sitting on site that was never unloaded accrues nothing,
        however long it stays. Arguable — but it is the current contract, and it should
        not change by accident."""
        result = DetentionCalculator.calculate_detention(
            check_in_at=at(0), unloaded_at=None, check_out_at=at(10_000),
            hourly_rate=RATE, free_minutes=FREE,
        )
        assert result["is_detention"] is False
        assert result["detention_charge"] == 0.0

    def test_clock_skew_never_produces_a_negative_charge(self):
        """Check-out before check-in is bad data, not a credit note. The elapsed time goes
        negative, and the free-time comparison has to absorb it."""
        result = DetentionCalculator.calculate_detention(
            check_in_at=at(60), unloaded_at=at(30), check_out_at=at(0),
            hourly_rate=RATE, free_minutes=FREE,
        )
        assert result["detention_charge"] == 0.0
        assert result["is_detention"] is False

    def test_an_open_stay_is_measured_to_now(self):
        """No check-out yet: the charge accrues against the current time. Uses a check-in
        far enough back that the assertion cannot be flaky."""
        check_in = datetime.now(timezone.utc) - timedelta(minutes=FREE + 60)
        result = DetentionCalculator.calculate_detention(
            check_in_at=check_in, unloaded_at=check_in, check_out_at=None,
            hourly_rate=RATE, free_minutes=FREE,
        )
        assert result["is_detention"] is True
        assert 59 <= result["detention_minutes"] <= 61


class TestNaiveTimestampsDoNotRaise:
    """FS-391. Every one of these raised TypeError before the fix; on SQLite that is the
    ONLY shape, so the dev path could not check a trailer out at all."""

    def test_a_naive_check_in_against_an_open_stay(self):
        check_in = (datetime.now(timezone.utc) - timedelta(minutes=FREE + 60)).replace(
            tzinfo=None
        )
        result = DetentionCalculator.calculate_detention(
            check_in_at=check_in, unloaded_at=check_in, check_out_at=None,
            hourly_rate=RATE, free_minutes=FREE,
        )
        assert result["is_detention"] is True

    def test_a_naive_check_in_with_an_aware_check_out(self):
        """The exact mix `_finalize_wait_time` creates: it sets `check_out_at` to
        `datetime.now(timezone.utc)` and leaves `check_in_at` as the driver stored it."""
        result = DetentionCalculator.calculate_detention(
            check_in_at=at(0, aware=False), unloaded_at=at(30, aware=False),
            check_out_at=at(180), hourly_rate=RATE, free_minutes=FREE,
        )
        assert result["detention_charge"] == 60.0

    def test_naive_and_aware_agree_on_the_number(self):
        """The fix must not change WHAT is billed, only stop the crash. A helper that
        guessed local time instead of UTC would shift every charge by the host's offset —
        and pass a test that only checked it did not raise."""
        aware = DetentionCalculator.calculate_detention(
            check_in_at=at(0), unloaded_at=at(30), check_out_at=at(180),
            hourly_rate=RATE, free_minutes=FREE,
        )
        naive = DetentionCalculator.calculate_detention(
            check_in_at=at(0, aware=False), unloaded_at=at(30, aware=False),
            check_out_at=at(180, aware=False), hourly_rate=RATE, free_minutes=FREE,
        )
        assert aware["detention_charge"] == naive["detention_charge"] == 60.0

    def test_demurrage_survives_naive_timestamps_too(self):
        result = DetentionCalculator.calculate_demurrage(
            docked_at=at(0, aware=False), unloaded_at=at(120, aware=False),
            hourly_rate=RATE, free_minutes=60,
        )
        assert result["demurrage_charge"] == 60.0


class TestDemurrageIsTimeToUnloadNotTimeOnSite:
    """A different clock from detention, and conflating them would bill twice for one
    delay: demurrage runs from DOCKED to UNLOADED, detention from CHECK-IN to CHECK-OUT."""

    def test_it_measures_from_docked_to_unloaded(self):
        result = DetentionCalculator.calculate_demurrage(
            docked_at=at(60), unloaded_at=at(180), hourly_rate=RATE, free_minutes=60,
        )
        assert result["demurrage_minutes"] == 60
        assert result["demurrage_charge"] == 60.0

    def test_never_docked_is_never_charged(self):
        result = DetentionCalculator.calculate_demurrage(
            docked_at=None, unloaded_at=at(180), hourly_rate=RATE,
        )
        assert result["is_demurrage"] is False

    def test_still_unloading_is_not_yet_charged(self):
        """Unlike detention, demurrage does NOT accrue to `now` while open — it needs both
        ends. Pinned because the two functions look symmetrical and are not."""
        result = DetentionCalculator.calculate_demurrage(
            docked_at=at(0), unloaded_at=None, hourly_rate=RATE,
        )
        assert result["is_demurrage"] is False
        assert result["demurrage_charge"] == 0.0

    def test_inside_its_own_free_window_is_free(self):
        result = DetentionCalculator.calculate_demurrage(
            docked_at=at(0), unloaded_at=at(45), hourly_rate=RATE, free_minutes=60,
        )
        assert result["is_demurrage"] is False


class TestTheDefaultsAreWhatTheCallerFallsBackTo:
    def test_the_documented_defaults_have_not_moved(self):
        """`_finalize_wait_time` uses these whenever a wait-time row has no contracted
        rate, so they are a real billing figure and not decoration."""
        assert DetentionCalculator.DEFAULT_DETENTION_RATE == 50.0
        assert DetentionCalculator.DEFAULT_DEMURRAGE_RATE == 75.0
        assert DetentionCalculator.FREE_TIME_MINUTES == 120

    def test_calling_without_a_rate_uses_the_default(self):
        result = DetentionCalculator.calculate_detention(
            check_in_at=at(0), unloaded_at=at(30), check_out_at=at(180),
        )
        # 60 minutes past the default 120-minute window, at $50/h.
        assert result["detention_charge"] == 50.0
