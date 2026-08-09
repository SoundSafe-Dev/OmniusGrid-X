"""
ERP Webhook Receiver

Generic webhook receiver infrastructure for ERP systems with:
- HMAC signature verification
- IP whitelisting
- Event type routing
- Deduplication and idempotency handling
- Webhook replay capability
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import hmac
import hashlib
import ipaddress
from fastapi import HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import structlog

from app.db.models import ERPIntegrationEvent
from app.db.database import get_db

logger = structlog.get_logger()


class ERPWebhookReceiver:
    """
    Generic webhook receiver for ERP systems.
    
    Handles incoming webhooks from various ERP platforms with
    security validation, deduplication, and event routing.
    """
    
    def __init__(self, integration_id: str, organization_id: str):
        self.integration_id = integration_id
        self.organization_id = organization_id
        self._ip_whitelist: Optional[List[str]] = None
        self._webhook_secret: Optional[str] = None
        self._event_processors: Dict[str, callable] = {}
        
        logger.info(
            "webhook_receiver_initialized",
            integration_id=integration_id,
            organization_id=organization_id
        )
    
    def configure(
        self,
        webhook_secret: Optional[str] = None,
        ip_whitelist: Optional[List[str]] = None
    ):
        """
        Configure webhook receiver security settings.
        
        Args:
            webhook_secret: Secret for HMAC signature verification
            ip_whitelist: List of allowed IP addresses/CIDR ranges
        """
        self._webhook_secret = webhook_secret
        self._ip_whitelist = ip_whitelist
        
        logger.info(
            "webhook_receiver_configured",
            has_secret=bool(webhook_secret),
            ip_whitelist_count=len(ip_whitelist) if ip_whitelist else 0
        )
    
    def register_event_processor(self, event_type: str, processor: callable):
        """
        Register a processor function for a specific event type.
        
        Args:
            event_type: Event type to process
            processor: Async function to process the event
        """
        self._event_processors[event_type] = processor
        logger.info(
            "event_processor_registered",
            event_type=event_type
        )
    
    async def receive_webhook(
        self,
        request: Request,
        event_data: Dict[str, Any],
        x_webhook_signature: Optional[str] = Header(None),
        x_webhook_timestamp: Optional[str] = Header(None),
        x_event_type: Optional[str] = Header(None),
        x_event_id: Optional[str] = Header(None),
        x_source_system: Optional[str] = Header(None)
    ) -> Dict[str, Any]:
        """
        Receive and process webhook from ERP system.
        
        Args:
            request: FastAPI request object
            event_data: Webhook payload
            x_webhook_signature: HMAC signature header
            x_webhook_timestamp: Timestamp header
            x_event_type: Event type header
            x_event_id: Event ID header
            x_source_system: Source system header
            
        Returns:
            Dict with processing status
            
        Raises:
            HTTPException: If validation fails
        """
        # Validate IP whitelist
        client_ip = request.client.host
        if not self._validate_ip_whitelist(client_ip):
            logger.warning(
                "webhook_ip_not_allowed",
                client_ip=client_ip,
                integration_id=self.integration_id
            )
            raise HTTPException(status_code=403, detail="IP not allowed")
        
        # Always validate. This was guarded by `if self._webhook_secret:`, so an
        # integration with no configured secret skipped verification entirely.
        # _validate_signature now fails closed on both a missing secret and a
        # missing signature.
        if not self._validate_signature(
            event_data,
            x_webhook_signature,
            x_webhook_timestamp
        ):
            logger.warning(
                "webhook_signature_invalid",
                integration_id=self.integration_id,
                has_secret=bool(self._webhook_secret),
                has_signature=bool(x_webhook_signature),
            )
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Validate timestamp to prevent replay attacks
        if x_webhook_timestamp:
            if not self._validate_timestamp(x_webhook_timestamp):
                logger.warning(
                    "webhook_timestamp_invalid",
                    timestamp=x_webhook_timestamp,
                    integration_id=self.integration_id
                )
                raise HTTPException(status_code=401, detail="Invalid timestamp")
        
        # Extract event metadata
        event_type = x_event_type or event_data.get("event_type")
        event_id = x_event_id or event_data.get("event_id")
        source_system = x_source_system or event_data.get("source_system")
        
        if not event_type or not event_id or not source_system:
            logger.error(
                "webhook_missing_required_fields",
                event_type=event_type,
                event_id=event_id,
                source_system=source_system
            )
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: event_type, event_id, source_system"
            )
        
        # Check for deduplication
        db = next(get_db())
        try:
            existing = await self._check_duplicate_event(
                db,
                source_system,
                event_id
            )
            
            if existing:
                logger.info(
                    "webhook_duplicate_event",
                    event_id=event_id,
                    source_system=source_system
                )
                return {
                    "status": "duplicate",
                    "message": "Event already processed",
                    "event_id": event_id
                }
            
            # Store event in database
            event_record = await self._store_event(
                db,
                event_type,
                event_id,
                source_system,
                event_data
            )
            
            # Route to appropriate processor
            processor = self._event_processors.get(event_type)
            if processor:
                try:
                    await processor(event_data, event_record.id)
                    await self._update_event_status(
                        db,
                        event_record.id,
                        "completed"
                    )
                except Exception as e:
                    logger.error(
                        "event_processor_failed",
                        event_type=event_type,
                        event_id=event_id,
                        error=str(e)
                    )
                    await self._update_event_status(
                        db,
                        event_record.id,
                        "failed",
                        str(e)
                    )
            else:
                logger.warning(
                    "no_processor_for_event_type",
                    event_type=event_type
                )
                await self._update_event_status(
                    db,
                    event_record.id,
                    "pending"
                )
            
            return {
                "status": "received",
                "message": "Event received and processed",
                "event_id": event_id,
                "event_record_id": str(event_record.id)
            }
            
        finally:
            await db.close()
    
    def _validate_ip_whitelist(self, client_ip: str) -> bool:
        """
        Validate client IP against whitelist.
        
        Args:
            client_ip: Client IP address
            
        Returns:
            bool: True if IP is allowed
        """
        if not self._ip_whitelist:
            # No whitelist configured, allow all
            return True
        
        try:
            client_addr = ipaddress.ip_address(client_ip)
            
            for allowed in self._ip_whitelist:
                try:
                    # Check if it's a CIDR range
                    if "/" in allowed:
                        network = ipaddress.ip_network(allowed, strict=False)
                        if client_addr in network:
                            return True
                    else:
                        # Exact IP match
                        if client_addr == ipaddress.ip_address(allowed):
                            return True
                except ValueError:
                    logger.warning(
                        "invalid_ip_in_whitelist",
                        ip=allowed
                    )
                    continue
            
            return False
            
        except ValueError:
            logger.error(
                "invalid_client_ip",
                client_ip=client_ip
            )
            return False
    
    def _validate_signature(
        self,
        event_data: Dict[str, Any],
        signature: Optional[str],
        timestamp: Optional[str]
    ) -> bool:
        """
        Validate HMAC signature.
        
        Args:
            event_data: Event payload
            signature: X-Webhook-Signature header
            timestamp: X-Webhook-Timestamp header
            
        Returns:
            bool: True if signature is valid
        """
        # Fails closed. This returned True when the signature header was absent,
        # so a caller could bypass verification entirely by simply omitting
        # X-Webhook-Signature — even with a secret configured. Nothing currently
        # routes to this class (sap_webhook_integration.py is unreferenced), but
        # app/api/erp_webhooks.py cites it as the reference implementation.
        if not signature or not self._webhook_secret:
            return False

        # DELEGATED, so the two implementations cannot drift.
        #
        # This used to hash `json.dumps(event_data, sort_keys=True)` -- the parsed
        # payload re-serialised with sorted keys. No ERP vendor signs a canonicalised
        # re-serialisation of its own payload; they sign the exact bytes they send.
        # Key order, whitespace and number formatting all differ, so the digest could
        # never match a real delivery and every genuine webhook was rejected.
        #
        # `event_data` here is already parsed, so the raw bytes are gone. Callers must
        # pass them; a dict is re-encoded compactly as a best effort and will NOT
        # match a real vendor signature -- which is correct, because at that point we
        # genuinely cannot verify one.
        from app.api.erp_webhooks import verify_signature

        raw_body = event_data if isinstance(event_data, (bytes, bytearray)) else None
        if raw_body is None:
            import json

            raw_body = json.dumps(event_data, separators=(",", ":")).encode()

        return verify_signature(self._webhook_secret, raw_body, signature)
    
    def _validate_timestamp(self, timestamp: str) -> bool:
        """
        Validate timestamp to prevent replay attacks.
        
        Args:
            timestamp: Timestamp string
            
        Returns:
            bool: True if timestamp is valid (within 5 minutes)
        """
        try:
            # Parse timestamp (ISO format)
            event_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            current_time = datetime.now(timezone.utc)
            
            # Check if timestamp is within 5 minutes
            time_diff = abs((current_time - event_time).total_seconds())
            
            return time_diff <= 300  # 5 minutes
            
        except ValueError:
            logger.error(
                "invalid_timestamp_format",
                timestamp=timestamp
            )
            return False
    
    async def _check_duplicate_event(
        self,
        db: AsyncSession,
        source_system: str,
        event_id: str
    ) -> Optional[ERPIntegrationEvent]:
        """
        Check if event has already been processed.
        
        Args:
            db: Database session
            source_system: Source system name
            event_id: Event ID
            
        Returns:
            Existing event record or None
        """
        result = await db.execute(
            select(ERPIntegrationEvent).where(
                and_(
                    ERPIntegrationEvent.source_system == source_system,
                    ERPIntegrationEvent.event_id == event_id,
                    ERPIntegrationEvent.processing_status == "completed"
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def _store_event(
        self,
        db: AsyncSession,
        event_type: str,
        event_id: str,
        source_system: str,
        event_data: Dict[str, Any]
    ) -> ERPIntegrationEvent:
        """
        Store event in database.
        
        Args:
            db: Database session
            event_type: Event type
            event_id: Event ID
            source_system: Source system
            event_data: Event payload
            
        Returns:
            Created event record
        """
        event = ERPIntegrationEvent(
            organization_id=self.organization_id,
            integration_id=self.integration_id,
            event_type=event_type,
            event_id=event_id,
            source_system=source_system,
            entity_type=event_data.get("entity_type"),
            entity_id=event_data.get("entity_id"),
            event_data=event_data,
            processing_status="pending"
        )
        
        db.add(event)
        await db.commit()
        await db.refresh(event)
        
        logger.info(
            "event_stored",
            event_id=event_id,
            event_type=event_type,
            record_id=str(event.id)
        )
        
        return event
    
    async def _update_event_status(
        self,
        db: AsyncSession,
        event_record_id: str,
        status: str,
        error_message: Optional[str] = None
    ):
        """
        Update event processing status.
        
        Args:
            db: Database session
            event_record_id: Event record ID
            status: New status
            error_message: Optional error message
        """
        result = await db.execute(
            select(ERPIntegrationEvent).where(
                ERPIntegrationEvent.id == event_record_id
            )
        )
        event = result.scalar_one_or_none()
        
        if event:
            event.processing_status = status
            event.processed_at = datetime.now(timezone.utc)
            if error_message:
                event.error_message = error_message
            
            await db.commit()
            
            logger.info(
                "event_status_updated",
                event_record_id=event_record_id,
                status=status
            )
    
    async def replay_event(self, event_record_id: str) -> Dict[str, Any]:
        """
        Replay a failed event from the database.
        
        Args:
            event_record_id: Event record ID to replay
            
        Returns:
            Dict with replay status
        """
        db = next(get_db())
        try:
            result = await db.execute(
                select(ERPIntegrationEvent).where(
                    ERPIntegrationEvent.id == event_record_id
                )
            )
            event = result.scalar_one_or_none()
            
            if not event:
                raise HTTPException(
                    status_code=404,
                    detail="Event not found"
                )
            
            # Reset event status
            event.processing_status = "pending"
            event.retry_count += 1
            event.processed_at = None
            event.error_message = None
            
            await db.commit()
            
            # Process event
            processor = self._event_processors.get(event.event_type)
            if processor:
                try:
                    await processor(event.event_data, event.id)
                    await self._update_event_status(
                        db,
                        event.id,
                        "completed"
                    )
                except Exception as e:
                    logger.error(
                        "event_replay_failed",
                        event_id=event.event_id,
                        error=str(e)
                    )
                    await self._update_event_status(
                        db,
                        event.id,
                        "failed",
                        str(e)
                    )
            
            return {
                "status": "replayed",
                "event_id": event.event_id,
                "retry_count": event.retry_count
            }
            
        finally:
            await db.close()
