"""
ERP Error Handler

Error handling and retry mechanisms for ERP integrations:
- Exponential backoff retry logic
- Dead letter queue for permanently failed events
- Error categorization (transient vs permanent)
- Automatic retry with configurable limits
- Alerting for permanent failures
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.db.models import ERPIntegrationEvent

logger = structlog.get_logger()


class ErrorCategory(Enum):
    """Error categories for classification"""
    TRANSIENT = "transient"  # Retryable errors (network, rate limits)
    PERMANENT = "permanent"  # Non-retryable errors (auth, invalid data)
    UNKNOWN = "unknown"  # Unclassified errors


class ERPErrorHandler:
    """
    Error handler for ERP integrations.
    
    Categorizes errors, manages retry logic, and handles
    dead letter queue for permanently failed events.
    """
    
    def __init__(self, organization_id: str, integration_id: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        self._retry_config = {
            "max_retries": 3,
            "backoff_multiplier": 2.0,
            "initial_delay": 1.0
        }
        self._alert_threshold = 5  # Alert after N permanent failures
        
        logger.info(
            "error_handler_initialized",
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    def configure_retry(
        self,
        max_retries: int = 3,
        backoff_multiplier: float = 2.0,
        initial_delay: float = 1.0
    ):
        """
        Configure retry behavior.
        
        Args:
            max_retries: Maximum number of retry attempts
            backoff_multiplier: Multiplier for exponential backoff
            initial_delay: Initial delay in seconds
        """
        self._retry_config = {
            "max_retries": max_retries,
            "backoff_multiplier": backoff_multiplier,
            "initial_delay": initial_delay
        }
        
        logger.info(
            "retry_config_updated",
            max_retries=max_retries,
            backoff_multiplier=backoff_multiplier,
            initial_delay=initial_delay
        )
    
    def categorize_error(self, error: Exception) -> ErrorCategory:
        """
        Categorize an error as transient or permanent.
        
        Args:
            error: Exception to categorize
            
        Returns:
            ErrorCategory: Category of the error
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()
        
        # Network errors (transient)
        network_errors = [
            "ConnectionError",
            "TimeoutError",
            "HTTPError",
            "RequestException",
            "ConnectTimeout",
            "ReadTimeout"
        ]
        
        if error_type in network_errors:
            return ErrorCategory.TRANSIENT
        
        # Rate limit errors (transient)
        if "rate limit" in error_msg or "429" in error_msg:
            return ErrorCategory.TRANSIENT
        
        # Timeout errors (transient)
        if "timeout" in error_msg:
            return ErrorCategory.TRANSIENT
        
        # Service unavailable (transient)
        if "503" in error_msg or "service unavailable" in error_msg:
            return ErrorCategory.TRANSIENT
        
        # Gateway timeout (transient)
        if "504" in error_msg or "gateway timeout" in error_msg:
            return ErrorCategory.TRANSIENT
        
        # Authentication errors (permanent)
        if "401" in error_msg or "unauthorized" in error_msg:
            return ErrorCategory.PERMANENT
        
        # Forbidden errors (permanent)
        if "403" in error_msg or "forbidden" in error_msg:
            return ErrorCategory.PERMANENT
        
        # Not found errors (permanent)
        if "404" in error_msg or "not found" in error_msg:
            return ErrorCategory.PERMANENT
        
        # Bad request errors (permanent)
        if "400" in error_msg or "bad request" in error_msg:
            return ErrorCategory.PERMANENT
        
        # Validation errors (permanent)
        if "validation" in error_msg or "invalid" in error_msg:
            return ErrorCategory.PERMANENT
        
        # Default to transient for unknown errors
        logger.warning(
            "error_categorization_unknown",
            error_type=error_type,
            error_message=error_msg
        )
        return ErrorCategory.UNKNOWN
    
    async def execute_with_retry(
        self,
        operation,
        *args,
        max_retries: Optional[int] = None,
        **kwargs
    ) -> Any:
        """
        Execute operation with exponential backoff retry logic.
        
        Args:
            operation: Async function to execute
            args: Positional arguments for operation
            max_retries: Override default max retries
            kwargs: Keyword arguments for operation
            
        Returns:
            Result of operation
            
        Raises:
            Exception: If all retries exhausted
        """
        max_retries = max_retries or self._retry_config["max_retries"]
        initial_delay = self._retry_config["initial_delay"]
        backoff_multiplier = self._retry_config["backoff_multiplier"]
        
        last_exception = None
        last_error_category = None
        
        for attempt in range(max_retries + 1):
            try:
                result = await operation(*args, **kwargs)
                
                logger.debug(
                    "operation_succeeded",
                    operation=operation.__name__,
                    attempt=attempt
                )
                
                return result
                
            except Exception as e:
                last_exception = e
                last_error_category = self.categorize_error(e)
                
                # If permanent error, don't retry
                if last_error_category == ErrorCategory.PERMANENT:
                    logger.error(
                        "permanent_error_no_retry",
                        operation=operation.__name__,
                        error=str(e),
                        error_type=type(e).__name__
                    )
                    raise
                
                # If unknown error, retry with caution
                if last_error_category == ErrorCategory.UNKNOWN:
                    logger.warning(
                        "unknown_error_retrying",
                        operation=operation.__name__,
                        attempt=attempt,
                        error=str(e)
                    )
                
                # If transient error, retry with backoff
                if attempt < max_retries:
                    delay = initial_delay * (backoff_multiplier ** attempt)
                    logger.warning(
                        "transient_error_retrying",
                        operation=operation.__name__,
                        attempt=attempt,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(e),
                        error_category=last_error_category.value
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "transient_error_all_retries_exhausted",
                        operation=operation.__name__,
                        max_retries=max_retries,
                        error=str(e)
                    )
                    raise
        
        raise last_exception
    
    async def handle_failed_event(
        self,
        db: AsyncSession,
        event_id: str,
        error: Exception,
        error_category: ErrorCategory
    ):
        """
        Handle a failed event based on error category.
        
        Args:
            db: Database session
            event_id: Event record ID
            error: Exception that occurred
            error_category: Category of the error
        """
        result = await db.execute(
            select(ERPIntegrationEvent).where(
                ERPIntegrationEvent.id == event_id
            )
        )
        event = result.scalar_one_or_none()
        
        if not event:
            logger.error(
                "event_not_found_for_error_handling",
                event_id=event_id
            )
            return
        
        # Increment retry count
        event.retry_count += 1
        
        if error_category == ErrorCategory.PERMANENT:
            # Move to dead letter queue
            event.processing_status = "failed"
            event.error_message = str(error)
            event.processed_at = datetime.utcnow()
            
            logger.error(
                "event_moved_to_dead_letter_queue",
                event_id=event.event_id,
                error=str(error)
            )
            
            # Check if alert threshold reached
            await self._check_alert_threshold(db)
            
        elif error_category == ErrorCategory.TRANSIENT:
            # Mark for retry
            event.processing_status = "retrying"
            event.error_message = str(error)
            
            logger.warning(
                "event_marked_for_retry",
                event_id=event.event_id,
                retry_count=event.retry_count,
                error=str(error)
            )
            
            # Check if max retries exceeded
            if event.retry_count >= self._retry_config["max_retries"]:
                event.processing_status = "failed"
                logger.error(
                    "event_max_retries_exceeded",
                    event_id=event.event_id,
                    retry_count=event.retry_count
                )
        
        else:
            # Unknown error - mark for retry with caution
            event.processing_status = "retrying"
            event.error_message = str(error)
            
            logger.warning(
                "event_unknown_error_marked_for_retry",
                event_id=event.event_id,
                error=str(error)
            )
        
        await db.commit()
    
    async def _check_alert_threshold(self, db: AsyncSession):
        """
        Check if permanent failure threshold has been reached and trigger alert.
        
        Args:
            db: Database session
        """
        # Count permanent failures in last hour
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        
        result = await db.execute(
            select(ERPIntegrationEvent).where(
                and_(
                    ERPIntegrationEvent.integration_id == self.integration_id,
                    ERPIntegrationEvent.processing_status == "failed",
                    ERPIntegrationEvent.processed_at >= one_hour_ago
                )
            )
        )
        failed_events = result.scalars().all()
        
        if len(failed_events) >= self._alert_threshold:
            logger.error(
                "permanent_failure_threshold_exceeded",
                integration_id=self.integration_id,
                failure_count=len(failed_events),
                threshold=self._alert_threshold
            )
            
            # TODO: Trigger alert (email, Slack, PagerDuty)
            await self._send_alert(len(failed_events))
    
    async def _send_alert(self, failure_count: int):
        """
        Send alert for permanent failures via the configured channels.

        Delivers through the shared notification service (real SMTP + Slack +
        webhook adapters), driven by the ERP_ALERT_* settings. Always logs;
        actual delivery is gated on ERP_ALERTS_ENABLED so it's a no-op until an
        operator configures recipients.

        Args:
            failure_count: Number of failures
        """
        message = f"ERP integration has {failure_count} permanent failures in the last hour"
        logger.critical(
            "erp_integration_alert",
            integration_id=self.integration_id,
            organization_id=self.organization_id,
            failure_count=failure_count,
            message=message,
        )

        from app.core.config import settings
        if not settings.ERP_ALERTS_ENABLED:
            return

        from app.services.notifications import notification_service

        event = {
            "title": f"ERP integration {self.integration_id} failing",
            "message": message,
            "severity": "critical",
            "organization_id": str(self.organization_id),
        }

        targets = []
        for recipient in (r.strip() for r in settings.ERP_ALERT_EMAIL_RECIPIENTS.split(",")):
            if recipient:
                targets.append(("email", recipient))
        if settings.ERP_ALERT_SLACK_WEBHOOK_URL:
            targets.append(("slack", settings.ERP_ALERT_SLACK_WEBHOOK_URL))
        if settings.ERP_ALERT_PAGERDUTY_WEBHOOK_URL:
            targets.append(("webhook", settings.ERP_ALERT_PAGERDUTY_WEBHOOK_URL))

        for channel, target in targets:
            # deliver() is sync and may block (SMTP); run off the event loop.
            ok, detail = await asyncio.to_thread(
                notification_service.deliver, channel, target, event
            )
            if not ok:
                logger.error("erp_alert_delivery_failed",
                             channel=channel, detail=detail,
                             integration_id=self.integration_id)
    
    async def get_dead_letter_queue(
        self,
        db: AsyncSession,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get events in dead letter queue (permanently failed).
        
        Args:
            db: Database session
            limit: Maximum number of events to return
            
        Returns:
            List of failed events
        """
        result = await db.execute(
            select(ERPIntegrationEvent).where(
                and_(
                    ERPIntegrationEvent.integration_id == self.integration_id,
                    ERPIntegrationEvent.processing_status == "failed"
                )
            ).order_by(
                ERPIntegrationEvent.created_at.desc()
            ).limit(limit)
        )
        events = result.scalars().all()
        
        return [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "event_id": event.event_id,
                "source_system": event.source_system,
                "error_message": event.error_message,
                "retry_count": event.retry_count,
                "created_at": event.created_at.isoformat(),
                "processed_at": event.processed_at.isoformat() if event.processed_at else None
            }
            for event in events
        ]
    
    async def retry_dead_letter_event(
        self,
        db: AsyncSession,
        event_record_id: str
    ) -> Dict[str, Any]:
        """
        Retry an event from dead letter queue.
        
        Args:
            db: Database session
            event_record_id: Event record ID to retry
            
        Returns:
            Dict with retry status
        """
        result = await db.execute(
            select(ERPIntegrationEvent).where(
                ERPIntegrationEvent.id == event_record_id
            )
        )
        event = result.scalar_one_or_none()
        
        if not event:
            raise ValueError(f"Event {event_record_id} not found")
        
        # Reset event for retry
        event.processing_status = "pending"
        event.retry_count = 0
        event.error_message = None
        event.processed_at = None
        
        await db.commit()
        
        logger.info(
            "dead_letter_event_retried",
            event_id=event.event_id,
            event_record_id=event_record_id
        )
        
        return {
            "status": "retried",
            "event_id": event.event_id,
            "event_record_id": str(event_record_id)
        }
    
    async def purge_dead_letter_queue(
        self,
        db: AsyncSession,
        older_than_hours: int = 24
    ) -> int:
        """
        Purge old events from dead letter queue.
        
        Args:
            db: Database session
            older_than_hours: Purge events older than this many hours
            
        Returns:
            Number of events purged
        """
        from sqlalchemy import delete
        
        cutoff_time = datetime.utcnow() - timedelta(hours=older_than_hours)
        
        result = await db.execute(
            delete(ERPIntegrationEvent).where(
                and_(
                    ERPIntegrationEvent.integration_id == self.integration_id,
                    ERPIntegrationEvent.processing_status == "failed",
                    ERPIntegrationEvent.processed_at < cutoff_time
                )
            )
        )
        
        purged_count = result.rowcount
        await db.commit()
        
        logger.info(
            "dead_letter_queue_purged",
            integration_id=self.integration_id,
            purged_count=purged_count,
            older_than_hours=older_than_hours
        )
        
        return purged_count
