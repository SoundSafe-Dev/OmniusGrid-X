"""An unusable timezone is a 400, not a 500 — in all three places that check one (FS-725).

`zoneinfo.ZoneInfo` resolves a name to a FILE, so its failures are the filesystem's — THREE
exception types, and three modules had each caught only one:

    ZoneInfo("Not/AZone")      ZoneInfoNotFoundError   — caught everywhere
    ZoneInfo("")               ValueError: keys must be normalized relative paths
    ZoneInfo("../etc/passwd")  ValueError: keys must refer to subdirectories
    ZoneInfo("x" * 300)        OSError: [Errno 63] File name too long

The third was found by THIS FILE against the first version of the fix. The `x * 300` case was
in the list below because it is the shape a fuzzer sends, not because anybody predicted it —
and the fix that had reasoned its way to ValueError still let it through as a 500. Reasoning
about a library's failure modes lists the ones you thought of; the test lists the ones that
happen.

So an empty timezone, or a traversal-shaped one, escaped as an unhandled ValueError while
every other bad value produced a clean rejection. `POST /compliance/reports/schedules`
answered **500** to `{"timezone": ""}` and 400 to everything else — one of eight operations
the contract gate found returning a bare `internal server error` once it could finish.

THE SAME THREE LINES IN THREE FILES, which is why this is a file rather than a one-line fix:
`api/compliance_reports.py`, `api/exports.py` and `services/maintenance_windows.py` each
hand-rolled the check, and each carried the same hole. They now share
`app.core.datetime_utils.canonical_timezone_key`, which returns the canonical key or None —
returning rather than raising, because the three callers own different error vocabularies (an
HTTPException, a `MaintenanceWindowValidationError`, and a scheduler that must not raise into
its loop) and imposing one would make two of them translate it back.

THE TRAVERSAL SHAPE IS WORTH NAMING even though `ZoneInfo` refuses it. A timezone name is
caller-supplied and reaches a filesystem lookup; the library saying no is the correct
outcome, and answering 500 tells the caller their input caused a server fault — which is
both untrue and the reply that invites somebody to keep probing.
"""

from __future__ import annotations

import pytest

from app.core.datetime_utils import canonical_timezone_key

pytestmark = pytest.mark.asyncio

#: Every shape that must be refused, with what makes it interesting.
UNUSABLE = [
    ("", "empty — ValueError, not ZoneInfoNotFoundError"),
    ("   ", "whitespace only, which strips to empty"),
    ("../etc/passwd", "traversal-shaped: reaches a filesystem lookup"),
    ("../../../../etc/passwd", "deeper traversal"),
    ("Not/AZone", "well-formed and unknown — the case everyone already handled"),
    ("x" * 300, "too long for the filesystem — OSError, the third exception type"),
]

USABLE = ["UTC", "Europe/London", "America/New_York", "Asia/Tokyo"]


class TestTheSharedCheck:
    @pytest.mark.parametrize("value,why", UNUSABLE, ids=[w for _v, w in UNUSABLE])
    def test_unusable_names_return_none(self, value: str, why: str):
        assert canonical_timezone_key(value) is None, f"{value!r} was accepted ({why})"

    @pytest.mark.parametrize("value", USABLE)
    def test_real_zones_return_their_canonical_key(self, value: str):
        """The denominator. A check that refuses everything would satisfy the class above
        and break every schedule in the product."""
        assert canonical_timezone_key(value) == value

    def test_none_is_not_a_crash(self):
        assert canonical_timezone_key(None) is None  # type: ignore[arg-type]


class TestTheComplianceRouteRefusesCleanly:
    """End to end, because the unit above cannot show what the ROUTE answers — and the
    route answering 500 was the finding."""

    BASE = {
        "name": "nightly gdpr",
        "framework": "gdpr",
        "format": "json",
        "frequency": "daily",
        "next_run_at": "2099-01-01T00:00:00Z",
    }

    @pytest.mark.parametrize("value,why", UNUSABLE, ids=[w for _v, w in UNUSABLE])
    async def test_it_is_a_400(self, client_a, value: str, why: str):
        response = await client_a.post(
            "/api/v1/compliance/reports/schedules", json={**self.BASE, "timezone": value}
        )
        assert response.status_code == 400, (
            f"timezone {value!r} answered {response.status_code}. A 500 says the request "
            f"was fine and the server broke; this request was not fine."
        )

    async def test_a_real_timezone_still_creates_the_schedule(self, client_a):
        response = await client_a.post(
            "/api/v1/compliance/reports/schedules",
            json={**self.BASE, "timezone": "Europe/London"},
        )
        assert response.status_code == 201, response.text[:300]


class TestTheOtherTwoCallers:
    """`exports` and `maintenance_windows` carried the same handler. The export ROUTE needs
    a template row before it reaches its validator, so that one is asserted at the validator
    it shares rather than through a fixture invented to reach it."""

    @pytest.mark.parametrize("value,why", UNUSABLE, ids=[w for _v, w in UNUSABLE])
    def test_maintenance_windows_refuses_rather_than_leaking(self, value: str, why: str):
        from app.services.maintenance_windows import (
            MaintenanceWindowValidationError,
            validate_timezone_name,
        )

        with pytest.raises(MaintenanceWindowValidationError):
            validate_timezone_name(value)

    @pytest.mark.parametrize("value,why", UNUSABLE, ids=[w for _v, w in UNUSABLE])
    def test_the_export_validator_raises_a_400(self, value: str, why: str):
        from fastapi import HTTPException

        from app.api.exports import _validate_schedule_fields

        with pytest.raises(HTTPException) as caught:
            _validate_schedule_fields(
                "daily",
                value,
                None,
                recipients=[],
                is_active=False,
            )
        assert caught.value.status_code == 400, (
            f"the export schedule validator raised {caught.value.status_code} for "
            f"timezone {value!r}"
        )
