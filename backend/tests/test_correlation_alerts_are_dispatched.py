"""A critical correlation alert must be sent, not logged (FS-351).

THE DEFECT. `_create_alert_notification` built an `alert_data` dict, wrote a
`logger.warning`, and returned

    f"alert-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

That identifier went into `result["alerts"]`, which `process_correlation_analysis` returns
to its caller — so a caller received alert references for alerts that were never sent, on a
path that classifies `severity: "critical"` above a risk score of 75.

This is the class `test_reporting_honesty.py` was written for: **not a crash, and not a
silent no-op, but a no-op that reports success with an identifier.** A crash gets fixed; an
empty return is at least detectable; a fabricated id is believed. The static scan there did
not catch this one because the function neither logs a `*_created`-style event nor claims a
count — it invents a *reference*, which is a different tell.

WHAT THE FIX USES. `notification_service.dispatch` already existed and already did the
work: it loads the tenant's subscription rules, delivers on the configured channels, records
the deliveries, and pushes failures into error-triage.

THE THREE OUTCOMES THIS FILE PINS, because only the first is an alert:

    delivered to someone   -> an identifier
    no subscribers matched -> None, and an info log. NOT an alert.
    dispatch raised        -> None, error-triage, and the committed correlation survives.

The second is the one most likely to regress into the old lie in a quieter form: an empty
delivery list is a legitimate outcome, and returning an id for it would put the fabricated
reference straight back.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.correlation_registry_integration import (
    correlation_registry_integration as integration,
)

ORG = uuid4()
USER = uuid4()


async def _alert(risk_score: float = 90.0):
    return await integration._create_alert_notification(
        analysis="Vibration correlates with a rising reject rate on line 3",
        risk_score=risk_score,
        recommended_actions=[{"action": "inspect bearing"}],
        organization_id=ORG,
        db=None,
        created_by=USER,
    )


class TestItActuallyDispatches:
    @pytest.mark.asyncio
    async def test_the_event_reaches_the_notification_service(self, monkeypatch):
        """The assertion the old code could not pass: it never called anything."""
        seen = {}

        async def _capture(event, organization_id=None):
            seen["event"] = event
            seen["organization_id"] = organization_id
            return [{"channel": "email", "delivered": True}]

        from app.services import notifications

        monkeypatch.setattr(notifications.notification_service, "dispatch", _capture)

        await _alert()
        assert seen, "no dispatch happened — the alert is still only being logged"
        assert seen["organization_id"] == str(ORG)
        assert seen["event"]["message"].startswith("Vibration correlates")

    @pytest.mark.asyncio
    async def test_a_high_risk_score_is_critical_severity(self, monkeypatch):
        captured = {}

        async def _capture(event, organization_id=None):
            captured.update(event)
            return [{"channel": "email", "delivered": True}]

        from app.services import notifications

        monkeypatch.setattr(notifications.notification_service, "dispatch", _capture)

        await _alert(risk_score=90.0)
        assert captured["severity"] == "critical"

        captured.clear()
        await _alert(risk_score=60.0)
        assert captured["severity"] == "high"

    @pytest.mark.asyncio
    async def test_the_tenant_is_always_passed(self, monkeypatch):
        """`dispatch` fails closed without an organisation — it refuses rather than
        fanning one tenant's alert out to every subscriber. Passing it explicitly is what
        keeps this caller out of that path."""
        captured = {}

        async def _capture(event, organization_id=None):
            captured["org"] = organization_id
            return [{"channel": "email", "delivered": True}]

        from app.services import notifications

        monkeypatch.setattr(notifications.notification_service, "dispatch", _capture)

        await _alert()
        assert captured["org"] is not None


class TestItDoesNotInventAReference:
    @pytest.mark.asyncio
    async def test_no_subscribers_returns_none_not_an_id(self, monkeypatch):
        """THE ONE MOST LIKELY TO REGRESS. An empty delivery list is legitimate — the
        tenant subscribed to nothing — and returning an identifier for it would be the
        original defect in a quieter form."""

        async def _none(event, organization_id=None):
            return []

        from app.services import notifications

        monkeypatch.setattr(notifications.notification_service, "dispatch", _none)

        assert await _alert() is None

    @pytest.mark.asyncio
    async def test_a_failed_delivery_returns_none(self, monkeypatch):
        async def _failed(event, organization_id=None):
            return [{"channel": "webhook", "delivered": False, "detail": "connect refused"}]

        from app.services import notifications

        monkeypatch.setattr(notifications.notification_service, "dispatch", _failed)

        assert await _alert() is None, (
            "a channel that refused the delivery is not an alert that was raised"
        )

    @pytest.mark.asyncio
    async def test_the_returned_value_is_never_a_timestamp_string(self, monkeypatch):
        """The old id was `alert-YYYYMMDDHHMMSS`, which looks like a reference and
        resolves to nothing."""

        async def _ok(event, organization_id=None):
            return [{"channel": "email", "delivered": True}]

        from app.services import notifications

        monkeypatch.setattr(notifications.notification_service, "dispatch", _ok)

        result = await _alert()
        assert result is not None
        assert not (isinstance(result, str) and result.startswith("alert-2")), (
            "the fabricated timestamp identifier is back"
        )


class TestAFailedDispatchDoesNotDiscardTheCorrelation:
    @pytest.mark.asyncio
    async def test_an_exception_is_caught_and_surfaced(self, monkeypatch):
        """The analysis and its correlations are already committed when this runs. Letting
        the exception out would throw away completed work over an undeliverable email."""
        reported = {}

        async def _boom(event, organization_id=None):
            raise RuntimeError("smtp unreachable")

        async def _report(exc, subsystem=None, operation=None, organization_id=None):
            reported["subsystem"] = subsystem
            reported["operation"] = operation

        from app.services import error_tracker as et
        from app.services import notifications

        monkeypatch.setattr(notifications.notification_service, "dispatch", _boom)
        monkeypatch.setattr(et.error_tracker, "report_subsystem_error", _report)

        assert await _alert() is None
        assert reported["subsystem"] == "correlation", (
            "a swallowed dispatch failure must reach error-triage, or a broken channel is "
            "invisible until someone reads the logs"
        )
