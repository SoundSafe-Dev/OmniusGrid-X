"""Reusable company SMTP transport for report delivery."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from email.message import EmailMessage
from typing import Final

import aiosmtplib
import structlog
from aiosmtplib import (
    SMTPAuthenticationError,
    SMTPConnectError,
    SMTPException,
    SMTPRecipientsRefused,
    SMTPResponseException,
    SMTPSenderRefused,
    SMTPServerDisconnected,
    SMTPTimeoutError,
)

from app.core.config import settings

logger = structlog.get_logger()

__all__ = [
    "EmailConfigurationError",
    "EmailDeliveryError",
    "send_email",
    "send_compliance_report_email",
]

_EMAIL_RE: Final[re.Pattern[str]] = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_RETRY_BACKOFF_SECONDS: Final[int] = 30


class EmailConfigurationError(ValueError):
    """SMTP settings or message inputs are invalid."""


class EmailDeliveryError(RuntimeError):
    """SMTP delivery failed after retryable attempts were exhausted."""


def _from_header() -> str:
    if settings.SMTP_FROM_NAME:
        return f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    return settings.SMTP_FROM_EMAIL


def _validate_smtp_configuration() -> None:
    if not settings.SMTP_HOST:
        raise EmailConfigurationError("SMTP_HOST is not configured")
    if not settings.SMTP_FROM_EMAIL:
        raise EmailConfigurationError("SMTP_FROM_EMAIL is not configured")
    if settings.SMTP_USE_TLS and settings.SMTP_START_TLS:
        raise EmailConfigurationError(
            "SMTP_USE_TLS and SMTP_START_TLS cannot both be enabled"
        )


def _validate_recipients(recipients: Sequence[str]) -> list[str]:
    if not recipients:
        raise EmailConfigurationError("At least one recipient is required")

    validated: list[str] = []
    for raw in recipients:
        address = raw.strip()
        if not address or not _EMAIL_RE.match(address):
            raise EmailConfigurationError(f"Invalid recipient address: {raw!r}")
        validated.append(address)
    return validated


def _build_message(
    recipients: Sequence[str],
    subject: str,
    text_body: str,
    html_body: str | None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = _from_header()
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body is not None:
        message.add_alternative(html_body, subtype="html")
    return message


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            SMTPConnectError,
            SMTPServerDisconnected,
            SMTPTimeoutError,
            ConnectionError,
            TimeoutError,
            OSError,
        ),
    ):
        return True

    if isinstance(exc, SMTPAuthenticationError):
        return False

    if isinstance(exc, (SMTPRecipientsRefused, SMTPSenderRefused)):
        return False

    if isinstance(exc, SMTPResponseException):
        return 400 <= exc.code < 500

    if isinstance(exc, SMTPException):
        return False

    return False


def _retry_delay(attempt: int) -> int:
    """Return bounded exponential backoff after a failed attempt."""
    exponent = min(attempt - 1, 5)
    return min(2**exponent, _MAX_RETRY_BACKOFF_SECONDS)


async def _deliver_once(message: EmailMessage) -> None:
    await aiosmtplib.send(
        message,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME or None,
        password=settings.SMTP_PASSWORD or None,
        use_tls=settings.SMTP_USE_TLS,
        start_tls=settings.SMTP_START_TLS,
    )


async def send_email(
    recipients: Sequence[str],
    subject: str,
    text_body: str,
    html_body: str | None = None,
    *,
    max_attempts: int = 3,
) -> None:
    """Send an email through the configured company SMTP server."""
    if max_attempts < 1:
        raise EmailConfigurationError("max_attempts must be at least 1")

    _validate_smtp_configuration()
    validated_recipients = _validate_recipients(recipients)
    message = _build_message(validated_recipients, subject, text_body, html_body)

    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            await _deliver_once(message)
            logger.info(
                "email_sent",
                recipient_count=len(validated_recipients),
                attempt=attempt,
            )
            return
        except EmailConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            transient = _is_transient_error(exc)
            logger.warning(
                "email_send_failed",
                attempt=attempt,
                max_attempts=max_attempts,
                transient=transient,
                error_type=type(exc).__name__,
                smtp_code=getattr(exc, "code", None),
            )
            if not transient:
                raise EmailDeliveryError(
                    "Email delivery failed with a permanent SMTP error"
                ) from exc
            if attempt == max_attempts:
                break
            await asyncio.sleep(_retry_delay(attempt))

    assert last_error is not None
    raise EmailDeliveryError(
        "Email delivery failed after exhausting retry attempts"
    ) from last_error


async def send_compliance_report_email(
    recipients: Sequence[str],
    framework: str,
    generated_at,
    download_url: str,
    expires_at,
    *,
    max_attempts: int = 3,
) -> None:
    """Send a compliance report notification with a signed download link."""
    from app.services.email_templates import build_compliance_report_email

    content = build_compliance_report_email(
        framework=framework,
        generated_at=generated_at,
        download_url=download_url,
        expires_at=expires_at,
    )
    await send_email(
        recipients,
        content.subject,
        content.text_body,
        content.html_body,
        max_attempts=max_attempts,
    )
