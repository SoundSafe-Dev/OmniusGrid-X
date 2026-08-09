"""A stored timestamp must not crash the verdict it decides (FS-400).

THREE INSTANCES OF ONE DEFECT IN ONE DAY, in three unrelated subsystems:

    app/api/health.py                       `MAX(time)` vs now  -> readiness reported a
                                            working database as a subsystem in error
    app/services/yard_management.py         check-in vs now     -> checking a trailer out
                                            raised before any charge was computed
    app/services/transportation_management  expiry vs now       -> the carrier-compliance
                                            endpoint returned 500

Each is the same line of code in different clothes: a column compared against
`datetime.now(timezone.utc)`.

WHY IT ONLY BITES ON THE DEV PATH. The columns are `DateTime(timezone=True)`, so Postgres
returns them aware and production is fine. SQLite has no timestamp type to preserve tzinfo
in, so on the database `make demo` builds every one of them is naive and the comparison
raises `TypeError: can't compare offset-naive and offset-aware datetimes`.

That makes it invisible to the real-DB suite by construction — those tests run against
Postgres, where the bug does not exist — and it is exactly the class a developer meets
first, on the documented offline demo.

WHAT THIS FILE ASSERTS, and what it deliberately does not. It exercises the pure functions
that do the comparing, with naive inputs, in the shape SQLite delivers. It does not need a
database: the defect is in the arithmetic, not the query, and a fixture that supplied aware
values would reproduce nothing.

UTC IS THE ASSUMPTION AND IT IS LOAD-BEARING. Everything writing these columns writes
`datetime.now(timezone.utc)`, so a naive value has already lost a tzinfo that said UTC.
Reading it as local time would move an expiry across midnight and flip a C-TPAT verdict for
a certificate expiring today — while passing any test that only checked it stopped raising.
So each case below asserts the VALUE, not merely the absence of an exception.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.transportation_management import HOSComplianceMonitor, _as_utc
from app.services.yard_management import DetentionCalculator
from app.services.yard_management import _as_utc as _yard_as_utc


def naive(days_from_now: float) -> datetime:
    """A timestamp the way SQLite hands it back: correct instant, no tzinfo."""
    return (datetime.now(timezone.utc) + timedelta(days=days_from_now)).replace(tzinfo=None)


def aware(days_from_now: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days_from_now)


class TestTheHelpersAgree:
    """Two modules, two copies. They must behave identically or a defect fixed in one
    subsystem stays open in the other — which is how this reached three instances."""

    @pytest.mark.parametrize("helper", [_as_utc, _yard_as_utc])
    def test_a_naive_value_becomes_utc(self, helper):
        value = datetime(2026, 8, 2, 12, 0, 0)
        assert helper(value) == datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize("helper", [_as_utc, _yard_as_utc])
    def test_an_aware_value_is_untouched(self, helper):
        value = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
        assert helper(value) is value

    @pytest.mark.parametrize("helper", [_as_utc, _yard_as_utc])
    def test_none_survives(self, helper):
        assert helper(None) is None

    @pytest.mark.parametrize("helper", [_as_utc, _yard_as_utc])
    def test_it_does_not_shift_the_instant(self, helper):
        """The assertion that catches a local-time reading. `replace(tzinfo=utc)` keeps the
        clock face; `astimezone(utc)` would move it by the host's offset — and both stop
        the crash, so a test that only checked for an exception cannot tell them apart."""
        assert helper(datetime(2026, 8, 2, 12, 0, 0)).hour == 12


class TestAMedicalCertificateVerdictSurvivesANaiveExpiry:
    """`check_compliance` decides whether a driver may legally drive."""

    def _driver(self, expires):
        return SimpleNamespace(
            id="drv-1",
            hos_drive_hours_today=5.0,
            hos_on_duty_hours_today=6.0,
            hos_cycle_hours=30.0,
            medical_cert_expires=expires,
        )

    def test_an_expired_certificate_is_a_violation(self):
        result = HOSComplianceMonitor().check_compliance(self._driver(naive(-10)))
        assert "Medical certificate expired" in result["violations"]
        assert result["is_compliant"] is False

    def test_a_certificate_expiring_soon_is_a_warning_not_a_violation(self):
        result = HOSComplianceMonitor().check_compliance(self._driver(naive(10)))
        assert result["violations"] == []
        assert any("expiring soon" in w for w in result["warnings"])

    def test_a_valid_certificate_is_neither(self):
        result = HOSComplianceMonitor().check_compliance(self._driver(naive(200)))
        assert result["violations"] == []
        assert not any("Medical certificate" in w for w in result["warnings"])

    def test_naive_and_aware_reach_the_same_verdict(self):
        """The one that matters. A helper reading local time would still stop the crash and
        would disagree here for any expiry near the boundary."""
        for offset in (-10, 10, 200):
            n = HOSComplianceMonitor().check_compliance(self._driver(naive(offset)))
            a = HOSComplianceMonitor().check_compliance(self._driver(aware(offset)))
            assert n["violations"] == a["violations"], f"disagreed at {offset} days"
            assert n["warnings"] == a["warnings"], f"disagreed at {offset} days"

    def test_no_certificate_is_missing_data_not_a_violation(self):
        """Unchanged behaviour, asserted because the fix touches this branch's neighbours:
        a driver with no certificate on file has not broken a rule."""
        result = HOSComplianceMonitor().check_compliance(self._driver(None))
        assert result["violations"] == []
        assert "No medical certificate on file" in result["missing_data"]
        assert result["assessable"] is False


class TestDetentionSurvivesNaiveTimestamps:
    """The yard half of the same class, kept here so the pair is visible in one place."""

    def test_an_open_stay_measured_against_now(self):
        check_in = naive(0) - timedelta(hours=4)
        result = DetentionCalculator.calculate_detention(
            check_in_at=check_in, unloaded_at=check_in, check_out_at=None,
            hourly_rate=60.0, free_minutes=120,
        )
        assert result["is_detention"] is True

    def test_naive_and_aware_bill_the_same(self):
        start_naive = datetime(2026, 8, 2, 8, 0, 0)
        start_aware = start_naive.replace(tzinfo=timezone.utc)
        n = DetentionCalculator.calculate_detention(
            start_naive, start_naive, start_naive + timedelta(hours=3), 60.0, 120
        )
        a = DetentionCalculator.calculate_detention(
            start_aware, start_aware, start_aware + timedelta(hours=3), 60.0, 120
        )
        assert n["detention_charge"] == a["detention_charge"] == 60.0
