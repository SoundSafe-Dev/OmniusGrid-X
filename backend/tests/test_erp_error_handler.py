"""Unit tests for ERP retry, failure handling, and alert dispatch gating."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from app.services import erp_error_handler as erp_error_handler_module
from app.services.erp_error_handler import ERPErrorHandler, ErrorCategory


@pytest.fixture
def erp_settings(monkeypatch):
    settings = SimpleNamespace(
        ERP_SYNC_MAX_RETRIES=3,
        ERP_ALERTS_ENABLED=True,
        ERP_ALERT_FAILURE_THRESHOLD=1,
        ERP_ALERT_EMAIL_RECIPIENTS="",
        ERP_ALERT_SLACK_WEBHOOK_URL="",
        ERP_ALERT_PAGERDUTY_WEBHOOK_URL="",
    )
    monkeypatch.setattr(erp_error_handler_module, "settings", settings)
    return settings


@pytest.fixture
def handler(erp_settings):
    return ERPErrorHandler(
        organization_id="org-1",
        integration_id="integration-1",
    )


class _ScalarList:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _ExecuteResult:
    def __init__(self, *, event=None, values=None):
        self._event = event
        self._values = values or []

    def scalar_one_or_none(self):
        return self._event

    def scalars(self):
        return _ScalarList(self._values)


class _FakeDB:
    def __init__(self, *, event, failed_events):
        self._event = event
        self._failed_events = failed_events
        self.execute_count = 0
        self.commit_count = 0

    async def execute(self, _statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return _ExecuteResult(event=self._event)
        return _ExecuteResult(values=self._failed_events)

    async def commit(self):
        self.commit_count += 1


def _event(**overrides):
    values = {
        "id": "event-1",
        "retry_count": 0,
        "error_message": None,
        "processing_status": "processing",
        "processed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_send_alert_skips_dispatch_when_alerts_disabled(handler, erp_settings):
    erp_settings.ERP_ALERTS_ENABLED = False
    erp_settings.ERP_ALERT_EMAIL_RECIPIENTS = "ops@example.com"
    erp_settings.ERP_ALERT_SLACK_WEBHOOK_URL = "https://hooks.example.test/slack"
    erp_settings.ERP_ALERT_PAGERDUTY_WEBHOOK_URL = "https://events.example.test/pagerduty"
    email_alert = AsyncMock()
    webhook_alert = AsyncMock()
    handler._send_email_alert = email_alert
    handler._send_webhook_alert = webhook_alert

    await handler._send_alert(failure_count=5)

    email_alert.assert_not_awaited()
    webhook_alert.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "recipients",
        "slack_webhook",
        "pagerduty_webhook",
        "expected_email_calls",
        "expected_webhook_urls",
    ),
    [
        ("", "", "", 0, []),
        (
            "ops@example.com, oncall@example.com",
            "https://hooks.example.test/slack",
            "https://events.example.test/pagerduty",
            1,
            [
                "https://hooks.example.test/slack",
                "https://events.example.test/pagerduty",
            ],
        ),
        (
            "",
            "https://hooks.example.test/slack",
            "",
            0,
            ["https://hooks.example.test/slack"],
        ),
    ],
)
async def test_send_alert_dispatches_only_configured_channels(
    handler,
    erp_settings,
    recipients,
    slack_webhook,
    pagerduty_webhook,
    expected_email_calls,
    expected_webhook_urls,
):
    erp_settings.ERP_ALERT_EMAIL_RECIPIENTS = recipients
    erp_settings.ERP_ALERT_SLACK_WEBHOOK_URL = slack_webhook
    erp_settings.ERP_ALERT_PAGERDUTY_WEBHOOK_URL = pagerduty_webhook
    email_alert = AsyncMock()
    webhook_alert = AsyncMock()
    handler._send_email_alert = email_alert
    handler._send_webhook_alert = webhook_alert

    await handler._send_alert(failure_count=5)

    assert email_alert.await_count == expected_email_calls
    assert [
        args.args[0] for args in webhook_alert.await_args_list
    ] == expected_webhook_urls


def test_categorize_error_marks_transient_permanent_and_unknown(handler):
    assert handler.categorize_error(TimeoutError("timed out")) == ErrorCategory.TRANSIENT
    assert (
        handler.categorize_error(RuntimeError("ERP returned 401 unauthorized"))
        == ErrorCategory.PERMANENT
    )
    assert handler.categorize_error(RuntimeError("unexpected shape")) == ErrorCategory.UNKNOWN


@pytest.mark.asyncio
async def test_execute_with_retry_retries_transient_errors(handler, monkeypatch):
    sleep = AsyncMock()
    operation = AsyncMock(side_effect=[TimeoutError("timeout"), TimeoutError("503"), "ok"])
    monkeypatch.setattr(erp_error_handler_module.asyncio, "sleep", sleep)

    result = await handler.execute_with_retry(operation, max_retries=3)

    assert result == "ok"
    assert operation.await_count == 3
    assert sleep.await_args_list == [call(1.0), call(2.0)]


@pytest.mark.asyncio
async def test_execute_with_retry_does_not_retry_permanent_errors(handler, monkeypatch):
    sleep = AsyncMock()
    operation = AsyncMock(side_effect=RuntimeError("400 invalid request"))
    monkeypatch.setattr(erp_error_handler_module.asyncio, "sleep", sleep)

    with pytest.raises(RuntimeError, match="400 invalid request"):
        await handler.execute_with_retry(operation, max_retries=3)

    assert operation.await_count == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_with_retry_raises_after_transient_retry_budget(handler, monkeypatch):
    sleep = AsyncMock()
    operation = AsyncMock(side_effect=TimeoutError("timeout"))
    monkeypatch.setattr(erp_error_handler_module.asyncio, "sleep", sleep)

    with pytest.raises(TimeoutError, match="timeout"):
        await handler.execute_with_retry(operation, max_retries=2)

    assert operation.await_count == 3
    assert sleep.await_args_list == [call(1.0), call(2.0)]


@pytest.mark.asyncio
async def test_handle_failed_event_marks_transient_event_retrying_before_retry_budget(
    handler,
):
    event = _event(retry_count=0)
    db = _FakeDB(event=event, failed_events=[])

    await handler.handle_failed_event(
        db,
        event_id=event.id,
        error=TimeoutError("timeout"),
        error_category=ErrorCategory.TRANSIENT,
    )

    assert event.retry_count == 1
    assert event.error_message == "timeout"
    assert event.processing_status == "retrying"
    assert event.processed_at is None
    assert db.commit_count == 1
    assert db.execute_count == 1


@pytest.mark.asyncio
async def test_handle_failed_event_marks_permanent_event_failed_and_checks_alerts(
    handler,
):
    event = _event(retry_count=0)
    db = _FakeDB(event=event, failed_events=[event])
    send_alert = AsyncMock()
    handler._send_alert = send_alert

    await handler.handle_failed_event(
        db,
        event_id=event.id,
        error=RuntimeError("401 unauthorized"),
        error_category=ErrorCategory.PERMANENT,
    )

    assert event.retry_count == 1
    assert event.error_message == "401 unauthorized"
    assert event.processing_status == "failed"
    assert event.processed_at is not None
    assert db.commit_count == 1
    assert db.execute_count == 2
    send_alert.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_handle_failed_event_marks_transient_event_failed_at_retry_budget(
    handler,
):
    event = _event(retry_count=2)
    db = _FakeDB(event=event, failed_events=[event])
    send_alert = AsyncMock()
    handler._send_alert = send_alert

    await handler.handle_failed_event(
        db,
        event_id=event.id,
        error=TimeoutError("timeout"),
        error_category=ErrorCategory.TRANSIENT,
    )

    assert event.retry_count == 3
    assert event.processing_status == "failed"
    assert event.processed_at is not None
    send_alert.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_alert_dispatch_failure_is_logged_and_does_not_break_failed_sync(
    handler,
    erp_settings,
    monkeypatch,
):
    erp_settings.ERP_ALERT_EMAIL_RECIPIENTS = "ops@example.com"
    erp_settings.ERP_ALERT_SLACK_WEBHOOK_URL = "https://hooks.example.test/slack"
    erp_settings.ERP_ALERT_PAGERDUTY_WEBHOOK_URL = "https://events.example.test/pagerduty"
    event = _event(retry_count=0)
    db = _FakeDB(event=event, failed_events=[event])
    handler._send_email_alert = AsyncMock(side_effect=RuntimeError("smtp down"))
    handler._send_webhook_alert = AsyncMock()
    warning = Mock()
    monkeypatch.setattr(erp_error_handler_module.logger, "warning", warning)

    await handler.handle_failed_event(
        db,
        event_id=event.id,
        error=RuntimeError("401 unauthorized"),
        error_category=ErrorCategory.PERMANENT,
    )

    assert event.processing_status == "failed"
    assert event.processed_at is not None
    assert db.commit_count == 1
    warning.assert_called_once_with(
        "erp_alert_dispatch_failed",
        channel="email",
        integration_id="integration-1",
        error="smtp down",
    )
    assert handler._send_webhook_alert.await_count == 2
