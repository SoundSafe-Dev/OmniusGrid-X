"""Unit tests for the reusable SMTP email service."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiosmtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPResponseException,
)

from app.services.email_templates import build_compliance_report_email
from app.services.email_service import (
    EmailConfigurationError,
    EmailDeliveryError,
    send_compliance_report_email,
    send_email,
)
from app.services.export_delivery import send_export_email


@pytest.fixture
def smtp_settings(monkeypatch):
    monkeypatch.setattr(
        "app.services.email_service.settings",
        SimpleNamespace(
            SMTP_HOST="smtp.example.com",
            SMTP_PORT=587,
            SMTP_USERNAME="smtp-user",
            SMTP_PASSWORD="smtp-pass",
            SMTP_FROM_EMAIL="reports@omniusgrid.local",
            SMTP_FROM_NAME="OmniusGrid Reports",
            SMTP_USE_TLS=False,
            SMTP_START_TLS=True,
        ),
    )


@pytest.fixture
def mock_send(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr("app.services.email_service.aiosmtplib.send", send)
    return send


def _captured_message(mock_send) -> EmailMessage:
    return mock_send.await_args.args[0]


def _captured_kwargs(mock_send) -> dict:
    return mock_send.await_args.kwargs


@pytest.mark.asyncio
async def test_send_plain_text_email_success(smtp_settings, mock_send):
    await send_email(
        ["recipient@example.com"],
        "Subject line",
        "Plain body",
    )

    message = _captured_message(mock_send)
    assert message["Subject"] == "Subject line"
    assert message.get_content().strip() == "Plain body"
    assert message.get_body(preferencelist=("html",)) is None


@pytest.mark.asyncio
async def test_send_multipart_plain_and_html_email(smtp_settings, mock_send):
    await send_email(
        ["recipient@example.com"],
        "Multipart",
        "Plain body",
        html_body="<p>HTML body</p>",
    )

    message = _captured_message(mock_send)
    plain_part = message.get_body(preferencelist=("plain",))
    assert plain_part is not None
    assert plain_part.get_content().strip() == "Plain body"
    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    assert html_part.get_content().strip() == "<p>HTML body</p>"


@pytest.mark.asyncio
async def test_send_uses_smtp_connection_arguments(smtp_settings, mock_send):
    await send_email(["recipient@example.com"], "Subject", "Body")

    kwargs = _captured_kwargs(mock_send)
    assert kwargs == {
        "hostname": "smtp.example.com",
        "port": 587,
        "username": "smtp-user",
        "password": "smtp-pass",
        "use_tls": False,
        "start_tls": True,
    }


@pytest.mark.asyncio
async def test_send_sets_from_to_and_subject_headers(smtp_settings, mock_send):
    await send_email(
        ["one@example.com", "two@example.com"],
        "Report ready",
        "Body",
    )

    message = _captured_message(mock_send)
    assert message["From"] == "OmniusGrid Reports <reports@omniusgrid.local>"
    assert message["To"] == "one@example.com, two@example.com"
    assert message["Subject"] == "Report ready"


@pytest.mark.asyncio
async def test_missing_smtp_host_raises_configuration_error(monkeypatch, mock_send):
    monkeypatch.setattr(
        "app.services.email_service.settings",
        SimpleNamespace(
            SMTP_HOST="",
            SMTP_PORT=587,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            SMTP_FROM_EMAIL="reports@omniusgrid.local",
            SMTP_FROM_NAME="",
            SMTP_USE_TLS=False,
            SMTP_START_TLS=True,
        ),
    )

    with pytest.raises(EmailConfigurationError, match="SMTP_HOST"):
        await send_email(["recipient@example.com"], "Subject", "Body")

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_missing_sender_address_raises_configuration_error(
    monkeypatch, mock_send
):
    monkeypatch.setattr(
        "app.services.email_service.settings",
        SimpleNamespace(
            SMTP_HOST="smtp.example.com",
            SMTP_PORT=587,
            SMTP_USERNAME="",
            SMTP_PASSWORD="",
            SMTP_FROM_EMAIL="",
            SMTP_FROM_NAME="",
            SMTP_USE_TLS=False,
            SMTP_START_TLS=True,
        ),
    )

    with pytest.raises(EmailConfigurationError, match="SMTP_FROM_EMAIL"):
        await send_email(["recipient@example.com"], "Subject", "Body")

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_empty_recipient_list_raises_configuration_error(
    smtp_settings, mock_send
):
    with pytest.raises(EmailConfigurationError, match="At least one recipient"):
        await send_email([], "Subject", "Body")

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_recipient_raises_configuration_error(smtp_settings, mock_send):
    with pytest.raises(EmailConfigurationError, match="Invalid recipient"):
        await send_email(["not-an-email"], "Subject", "Body")

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_retry_count_raises_configuration_error(
    smtp_settings, mock_send
):
    with pytest.raises(EmailConfigurationError, match="max_attempts"):
        await send_email(["recipient@example.com"], "Subject", "Body", max_attempts=0)

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_transient_failure_then_success(
    smtp_settings, mock_send, monkeypatch
):
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.email_service.asyncio.sleep", sleep)
    mock_send.side_effect = [
        SMTPConnectError("connection reset"),
        None,
    ]

    await send_email(["recipient@example.com"], "Subject", "Body", max_attempts=3)

    assert mock_send.await_count == 2
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_transient_failure_exhausts_all_attempts(
    smtp_settings, mock_send, monkeypatch
):
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.email_service.asyncio.sleep", sleep)
    mock_send.side_effect = SMTPConnectError("connection reset")

    with pytest.raises(EmailDeliveryError, match="exhausting retry attempts"):
        await send_email(["recipient@example.com"], "Subject", "Body", max_attempts=3)

    assert mock_send.await_count == 3
    assert sleep.await_count == 2
    sleep.assert_any_await(1)
    sleep.assert_any_await(2)


@pytest.mark.asyncio
async def test_retry_backoff_supports_more_than_three_attempts(
    smtp_settings, mock_send, monkeypatch
):
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.email_service.asyncio.sleep", sleep)
    mock_send.side_effect = SMTPConnectError("connection reset")

    with pytest.raises(EmailDeliveryError, match="exhausting retry attempts"):
        await send_email(["recipient@example.com"], "Subject", "Body", max_attempts=4)

    assert mock_send.await_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2, 4]


@pytest.mark.asyncio
async def test_smtp_4xx_response_is_retried(smtp_settings, mock_send, monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.email_service.asyncio.sleep", sleep)
    mock_send.side_effect = [
        SMTPResponseException(421, "Service not available"),
        None,
    ]

    await send_email(["recipient@example.com"], "Subject", "Body", max_attempts=3)

    assert mock_send.await_count == 2
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_smtp_5xx_response_fails_immediately(smtp_settings, mock_send):
    mock_send.side_effect = SMTPResponseException(550, "Mailbox unavailable")

    with pytest.raises(EmailDeliveryError, match="permanent SMTP error"):
        await send_email(["recipient@example.com"], "Subject", "Body", max_attempts=3)

    assert mock_send.await_count == 1


@pytest.mark.asyncio
async def test_authentication_failure_fails_immediately(smtp_settings, mock_send):
    mock_send.side_effect = SMTPAuthenticationError(535, "Authentication failed")

    with pytest.raises(EmailDeliveryError, match="permanent SMTP error"):
        await send_email(["recipient@example.com"], "Subject", "Body", max_attempts=3)

    assert mock_send.await_count == 1


@pytest.mark.asyncio
async def test_backoff_does_not_sleep_after_final_failure(
    smtp_settings, mock_send, monkeypatch
):
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.email_service.asyncio.sleep", sleep)
    mock_send.side_effect = SMTPConnectError("connection reset")

    with pytest.raises(EmailDeliveryError):
        await send_email(["recipient@example.com"], "Subject", "Body", max_attempts=2)

    assert mock_send.await_count == 2
    sleep.assert_awaited_once_with(1)


def test_compliance_template_includes_required_metadata():
    generated_at = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
    download_url = "https://reports.example.com/download/abc123"

    content = build_compliance_report_email(
        framework="iso27001",
        generated_at=generated_at,
        download_url=download_url,
        expires_at=expires_at,
    )

    assert "iso27001" in content.subject
    assert "iso27001" in content.text_body
    assert download_url in content.text_body
    assert "2026-06-10" in content.text_body
    assert "2026-06-11" in content.text_body
    assert "do not forward" in content.text_body.lower()
    assert download_url in content.html_body
    assert "OmniusGrid" in content.html_body


def test_compliance_html_escapes_dynamic_input():
    generated_at = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
    malicious_framework = 'soc2<script>alert("x")</script>'
    malicious_url = 'https://example.com/report?x=1&y="2"'

    content = build_compliance_report_email(
        framework=malicious_framework,
        generated_at=generated_at,
        download_url=malicious_url,
        expires_at=expires_at,
    )

    assert "<script>" not in content.html_body
    assert "&lt;script&gt;" in content.html_body
    assert malicious_url not in content.html_body
    assert malicious_framework in content.text_body


def test_compliance_plain_text_and_html_share_essential_information():
    generated_at = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
    download_url = "https://reports.example.com/download/abc123"

    content = build_compliance_report_email(
        framework="gdpr",
        generated_at=generated_at,
        download_url=download_url,
        expires_at=expires_at,
    )

    for essential in ("gdpr", download_url, "OmniusGrid", "do not forward"):
        assert essential.lower() in content.text_body.lower()
        assert essential.lower() in content.html_body.lower()


@pytest.mark.asyncio
async def test_send_compliance_report_email_delegates_to_send_email(
    smtp_settings, mock_send, monkeypatch
):
    delegated = AsyncMock()
    monkeypatch.setattr("app.services.email_service.send_email", delegated)

    generated_at = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    expires_at = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)

    await send_compliance_report_email(
        ["recipient@example.com"],
        "iso27001",
        generated_at,
        "https://reports.example.com/download/abc123",
        expires_at,
    )

    delegated.assert_awaited_once()
    args, kwargs = delegated.await_args
    assert kwargs["max_attempts"] == 3
    assert args[3] is not None
    assert "iso27001" in args[1]


@pytest.mark.asyncio
async def test_send_export_email_delegates_with_single_internal_attempt(
    smtp_settings, mock_send, monkeypatch
):
    delegated = AsyncMock()
    monkeypatch.setattr("app.services.email_service.send_email", delegated)

    await send_export_email(
        ["recipient@example.com"],
        "Daily telemetry",
        "https://reports.example.com/download/export-1",
    )

    delegated.assert_awaited_once()
    assert delegated.await_args.kwargs["max_attempts"] == 1
    assert delegated.await_args.args[1] == "OmniusGrid scheduled report: Daily telemetry"
    assert "Your scheduled report is ready." in delegated.await_args.args[2]
    assert "please do not forward it." in delegated.await_args.args[2]
    assert len(delegated.await_args.args) == 3


@pytest.mark.asyncio
async def test_live_smtp_delivery_smoke():
    if os.getenv("RUN_SMTP_INTEGRATION") != "1":
        pytest.skip("Set RUN_SMTP_INTEGRATION=1 to run live SMTP integration test")

    recipient = os.getenv("SMTP_TEST_RECIPIENT", "").strip()
    if not recipient:
        pytest.skip("Set SMTP_TEST_RECIPIENT to run live SMTP integration test")

    from app.core.config import settings

    if not settings.SMTP_HOST:
        pytest.skip("SMTP_HOST is not configured for live SMTP integration test")

    await send_email(
        [recipient],
        "OmniusGrid SMTP integration smoke test",
        "This is a harmless OmniusGrid SMTP integration smoke test.",
    )
