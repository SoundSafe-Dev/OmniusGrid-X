"""ERP retry and failure handling primitives."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import aiohttp
import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import ERPIntegrationEvent

logger = structlog.get_logger()


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class ERPErrorHandler:
    """Categorize ERP failures, update event state, and dispatch gated alerts."""

    def __init__(self, organization_id: str, integration_id: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        self._retry_config = {
            "max_retries": settings.ERP_SYNC_MAX_RETRIES,
            "backoff_multiplier": 2.0,
            "initial_delay": 1.0,
        }
        self._alert_threshold = settings.ERP_ALERT_FAILURE_THRESHOLD

    def categorize_error(self, error: Exception) -> ErrorCategory:
        error_type = type(error).__name__
        message = str(error).lower()

        if error_type in {
            "ConnectionError",
            "TimeoutError",
            "HTTPError",
            "RequestException",
            "ConnectTimeout",
            "ReadTimeout",
        }:
            return ErrorCategory.TRANSIENT
        if any(marker in message for marker in ("timeout", "rate limit", "429", "503", "504")):
            return ErrorCategory.TRANSIENT
        if any(marker in message for marker in ("400", "401", "403", "404", "unauthorized", "forbidden", "invalid")):
            return ErrorCategory.PERMANENT
        return ErrorCategory.UNKNOWN

    async def execute_with_retry(self, operation, *args, **kwargs) -> Any:
        max_retries = int(kwargs.pop("max_retries", self._retry_config["max_retries"]))
        initial_delay = float(self._retry_config["initial_delay"])
        multiplier = float(self._retry_config["backoff_multiplier"])

        last_exception: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await operation(*args, **kwargs)
            except Exception as exc:
                last_exception = exc
                category = self.categorize_error(exc)
                if category == ErrorCategory.PERMANENT or attempt >= max_retries:
                    raise
                await asyncio.sleep(initial_delay * (multiplier ** attempt))

        if last_exception:
            raise last_exception
        raise RuntimeError("ERP operation failed without an exception")

    async def handle_failed_event(
        self,
        db: AsyncSession,
        event_id: str,
        error: Exception,
        error_category: ErrorCategory | None = None,
    ) -> None:
        category = error_category or self.categorize_error(error)
        result = await db.execute(
            select(ERPIntegrationEvent).where(ERPIntegrationEvent.id == event_id)
        )
        event = result.scalar_one_or_none()
        if not event:
            logger.error("erp_failed_event_missing", event_id=event_id)
            return

        event.retry_count = (event.retry_count or 0) + 1
        event.error_message = str(error)

        if category == ErrorCategory.PERMANENT:
            event.processing_status = "failed"
            event.processed_at = datetime.utcnow()
        elif event.retry_count >= self._retry_config["max_retries"]:
            event.processing_status = "failed"
            event.processed_at = datetime.utcnow()
        else:
            event.processing_status = "retrying"

        await db.commit()

        if event.processing_status == "failed":
            await self._check_alert_threshold(db)

    async def _check_alert_threshold(self, db: AsyncSession) -> None:
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        result = await db.execute(
            select(ERPIntegrationEvent).where(
                and_(
                    ERPIntegrationEvent.integration_id == self.integration_id,
                    ERPIntegrationEvent.processing_status == "failed",
                    ERPIntegrationEvent.processed_at >= one_hour_ago,
                )
            )
        )
        failure_count = len(result.scalars().all())
        if failure_count >= self._alert_threshold:
            await self._send_alert(failure_count)

    async def _send_alert(self, failure_count: int) -> None:
        payload = {
            "organization_id": self.organization_id,
            "integration_id": self.integration_id,
            "failure_count": failure_count,
            "window": "1h",
            "message": "ERP integration permanent failure threshold exceeded",
        }

        logger.critical("erp_integration_alert", **payload)

        if not settings.ERP_ALERTS_ENABLED:
            return

        await self._send_email_alert(payload)
        await self._send_webhook_alert(settings.ERP_ALERT_SLACK_WEBHOOK_URL, payload)
        await self._send_webhook_alert(settings.ERP_ALERT_PAGERDUTY_WEBHOOK_URL, payload)

    async def _send_email_alert(self, payload: dict[str, Any]) -> None:
        recipients = [
            item.strip()
            for item in settings.ERP_ALERT_EMAIL_RECIPIENTS.split(",")
            if item.strip()
        ]
        if not recipients:
            return

        try:
            from app.services.email_service import send_email

            await send_email(
                recipients=recipients,
                subject="ERP integration failure threshold exceeded",
                text_body=(
                    "ERP integration failure threshold exceeded.\n\n"
                    f"Organization: {payload['organization_id']}\n"
                    f"Integration: {payload['integration_id']}\n"
                    f"Failures: {payload['failure_count']} in {payload['window']}\n"
                ),
                max_attempts=1,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "erp_alert_email_failed",
                integration_id=self.integration_id,
                error=str(exc),
            )

    async def _send_webhook_alert(self, webhook_url: str, payload: dict[str, Any]) -> None:
        if not webhook_url:
            return
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload, timeout=10) as response:
                    if response.status >= 300:
                        logger.warning(
                            "erp_alert_webhook_failed",
                            status_code=response.status,
                            integration_id=self.integration_id,
                        )
        except Exception as exc:
            logger.warning(
                "erp_alert_webhook_error",
                integration_id=self.integration_id,
                error=str(exc),
            )
