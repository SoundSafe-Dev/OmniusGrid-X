"""FS-110: converged subsystems report into error-triage.

HTTP exceptions reach the error tracker via the error-tracking middleware, but
the rul/twin/notification subsystems catch-and-continue — their failures used to
live only in a warning log. These tests lock in that such failures now land in
the tracker's pending buffer under a synthetic ``subsystem:<name>.<op>`` route,
so error-triage surfaces them.
"""

from __future__ import annotations

import pytest

from app.services.error_tracker import ErrorTracker


@pytest.mark.asyncio
async def test_report_subsystem_error_routes_under_synthetic_route():
    tracker = ErrorTracker()
    await tracker.report_subsystem_error(
        RuntimeError("boom"),
        subsystem="rul",
        operation="notify",
        organization_id="org-1",
    )

    pending = list(tracker._pending.values())
    assert len(pending) == 1
    entry = pending[0]
    assert entry.route == "subsystem:rul.notify"
    assert entry.method == "INTERNAL"
    assert entry.exception_type == "RuntimeError"
    assert entry.organization_id == "org-1"
    assert entry.count == 1


@pytest.mark.asyncio
async def test_repeated_subsystem_errors_aggregate_by_fingerprint():
    tracker = ErrorTracker()
    for _ in range(3):
        await tracker.report_subsystem_error(
            ValueError("same"),
            subsystem="twin",
            operation="emit_recommendation",
        )
    pending = list(tracker._pending.values())
    assert len(pending) == 1
    assert pending[0].count == 3
    assert pending[0].route == "subsystem:twin.emit_recommendation"


@pytest.mark.asyncio
async def test_notification_delivery_failure_is_reported(monkeypatch):
    """A failed channel delivery lands in error-triage, tagged per channel."""
    from app.services import notifications as notif_module
    from app.services.error_tracker import error_tracker

    # Snapshot + isolate the singleton's pending buffer for this test.
    saved = dict(error_tracker._pending)
    error_tracker._pending.clear()

    service = notif_module.NotificationService()

    # One matching rule whose channel adapter raises -> delivered=False.
    monkeypatch.setattr(service, "matches", lambda rule, event: True)

    def boom(target, event):
        raise RuntimeError("webhook 500")

    service.channels = {"webhook": boom}

    async def fake_load_rules(org_id):
        return [{"id": "sub-1", "channel": "webhook", "target": "https://x.invalid"}]

    async def noop_record(event, org_id, results):
        return None

    monkeypatch.setattr(service, "_load_rules", fake_load_rules)
    monkeypatch.setattr(service, "_record_deliveries", noop_record)

    try:
        results = await service.dispatch({"severity": "critical", "title": "t"}, organization_id="org-9")
        assert results and results[0]["delivered"] is False

        routes = {e.route for e in error_tracker._pending.values()}
        assert "subsystem:notifications.deliver.webhook" in routes
        entry = next(
            e for e in error_tracker._pending.values()
            if e.route == "subsystem:notifications.deliver.webhook"
        )
        assert entry.exception_type == "NotificationDeliveryError"
        assert entry.organization_id == "org-9"
    finally:
        error_tracker._pending.clear()
        error_tracker._pending.update(saved)
