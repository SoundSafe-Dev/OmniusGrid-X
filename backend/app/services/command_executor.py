"""
Command Executor Service - Queue processor for asset commands
Handles command queuing, execution tracking, and status updates
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, asdict
from enum import Enum
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.db.database import AsyncSessionLocal
from app.db.models import Command, Asset
from app.services.websocket_manager import websocket_manager
from app.core.config import settings

logger = structlog.get_logger()


class CommandStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class CommandResult:
    """Result of command execution"""
    success: bool
    message: str
    data: Optional[Dict] = None
    error_code: Optional[str] = None


class CommandExecutor:
    """
    Command execution orchestrator.
    
    Responsibilities:
    - Queue commands from API/clients
    - Track execution status
    - Interface with edge agents via Redpanda
    - Handle timeouts and retries
    - Broadcast status updates via WebSocket
    """
    
    def __init__(self):
        self._command_queue: asyncio.Queue = asyncio.Queue()
        self._pending_commands: Dict[str, Dict] = {}  # command_id -> command info
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._timeout_seconds = 60
        self._max_retries = 3
        self._producer: Optional[AIOKafkaProducer] = None
        self._ack_consumer: Optional[AIOKafkaConsumer] = None
        self._ack_consumer_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the command executor"""
        logger.info("command_executor_starting")
        self._running = True
        
        # Initialize Redpanda producer
        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=settings.REDPANDA_URL,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                acks='all',
                retries=3,
                compression_type='gzip'
            )
            await self._producer.start()
            logger.info("redpanda_producer_started", url=settings.REDPANDA_URL)
        except Exception as e:
            logger.error("redpanda_producer_start_failed", error=str(e))
            self._producer = None

        try:
            self._ack_consumer = AIOKafkaConsumer(
                settings.REDPANDA_COMMAND_ACK_TOPIC,
                bootstrap_servers=settings.REDPANDA_URL,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                group_id="opsgrid-command-executor",
                enable_auto_commit=True,
            )
            await self._ack_consumer.start()
            self._ack_consumer_task = asyncio.create_task(self._ack_consumer_loop())
            logger.info(
                "redpanda_command_ack_consumer_started",
                topic=settings.REDPANDA_COMMAND_ACK_TOPIC,
                url=settings.REDPANDA_URL,
            )
        except Exception as e:
            logger.error("redpanda_command_ack_consumer_start_failed", error=str(e))
            self._ack_consumer = None
        
        self._worker_task = asyncio.create_task(self._command_worker())
        
        # Start timeout monitor
        asyncio.create_task(self._timeout_monitor())
        
        logger.info("command_executor_started")
    
    async def stop(self):
        """Stop the command executor"""
        logger.info("command_executor_stopping")
        self._running = False
        
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        if self._ack_consumer_task:
            self._ack_consumer_task.cancel()
            try:
                await self._ack_consumer_task
            except asyncio.CancelledError:
                pass
        
        # Stop Redpanda producer
        if self._producer:
            try:
                await self._producer.stop()
                logger.info("redpanda_producer_stopped")
            except Exception as e:
                logger.error("redpanda_producer_stop_failed", error=str(e))

        if self._ack_consumer:
            try:
                await self._ack_consumer.stop()
                logger.info("redpanda_command_ack_consumer_stopped")
            except Exception as e:
                logger.error("redpanda_command_ack_consumer_stop_failed", error=str(e))
        
        logger.info("command_executor_stopped")
    
    async def submit_command(
        self,
        asset_id: str,
        command_type: str,  # 'tactical', 'operator', 'system'
        action_id: str,     # e.g., 'set_speed', 'pause_job', 'emergency_stop'
        parameters: Dict[str, Any],
        issued_by: Optional[str] = None,
        organization_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None
    ) -> str:
        """
        Submit a new command for execution.
        Returns command ID for tracking.
        """
        command_id = f"cmd_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{asset_id[:8]}"
        
        async with AsyncSessionLocal() as session:
            # Create command record
            command = Command(
                id=command_id,
                asset_id=asset_id,
                command_type=command_type,
                action_id=action_id,
                parameters=parameters,
                status=CommandStatus.PENDING.value,
                issued_by=issued_by,
                issued_at=datetime.utcnow()
            )
            session.add(command)
            await session.commit()
        
        # Queue for execution
        command_info = {
            'command_id': command_id,
            'asset_id': asset_id,
            'organization_id': organization_id,
            'command_type': command_type,
            'action_id': action_id,
            'parameters': parameters,
            'timeout': timeout_seconds or self._timeout_seconds,
            'retry_count': 0,
            'submitted_at': datetime.utcnow()
        }
        
        await self._command_queue.put(command_info)
        
        # Broadcast pending status
        if organization_id:
            await websocket_manager.publish_telemetry(
                organization_id=organization_id,
                asset_id=asset_id,
                telemetry_data={
                    'command_status': CommandStatus.PENDING.value,
                    'command_id': command_id,
                    'action': action_id
                }
            )
        
        logger.info(
            "command_submitted",
            command_id=command_id,
            asset_id=asset_id,
            action=action_id
        )
        
        return command_id
    
    async def get_command_status(self, command_id: str) -> Optional[Dict]:
        """Get current status of a command"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Command).where(Command.id == command_id)
            )
            command = result.scalar_one_or_none()
            
            if command:
                return {
                    'command_id': command.id,
                    'status': command.status,
                    'asset_id': str(command.asset_id),
                    'action': command.action_id,
                    'issued_at': command.issued_at.isoformat() if command.issued_at else None,
                    'executed_at': command.executed_at.isoformat() if command.executed_at else None,
                    'result': command.result
                }
        
        return None
    
    async def cancel_command(self, command_id: str, cancelled_by: str) -> bool:
        """Cancel a pending command"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Command).where(
                    Command.id == command_id,
                    Command.status.in_([CommandStatus.PENDING.value, CommandStatus.EXECUTING.value])
                )
            )
            command = result.scalar_one_or_none()
            
            if not command:
                return False
            
            command.status = CommandStatus.CANCELLED.value
            command.result = {'cancelled_by': cancelled_by, 'cancelled_at': datetime.utcnow().isoformat()}
            await session.commit()
            
            # Remove from pending queue if still there
            if command_id in self._pending_commands:
                del self._pending_commands[command_id]
            
            logger.info("command_cancelled", command_id=command_id, cancelled_by=cancelled_by)
            return True
    
    async def _command_worker(self):
        """Main worker loop processing commands"""
        while self._running:
            try:
                # Get next command from queue
                try:
                    command_info = await asyncio.wait_for(
                        self._command_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                command_id = command_info['command_id']
                
                # Track as pending
                self._pending_commands[command_id] = command_info
                
                # Execute command
                await self._execute_command(command_info)
                
                self._command_queue.task_done()
                
            except Exception as e:
                logger.error("command_worker_error", error=str(e))
    
    async def _execute_command(self, command_info: Dict):
        """Execute a single command"""
        command_id = command_info['command_id']
        asset_id = command_info['asset_id']
        organization_id = command_info.get('organization_id')
        action_id = command_info['action_id']
        parameters = command_info['parameters']
        
        try:
            # Update status to executing
            await self._update_command_status(
                command_id,
                CommandStatus.EXECUTING,
                result={'started_at': datetime.utcnow().isoformat()}
            )
            
            # Broadcast executing status
            if organization_id:
                await self._broadcast_command_status(
                    organization_id, asset_id, command_id,
                    CommandStatus.EXECUTING, action_id
                )
            
            result = await self._send_to_edge_agent(
                command_id=command_id,
                asset_id=asset_id,
                organization_id=organization_id,
                action_id=action_id,
                parameters=parameters,
                timeout_seconds=command_info["timeout"],
            )
            
            if result.success:
                logger.info(
                    "command_dispatched",
                    command_id=command_id,
                    asset_id=asset_id,
                    topic=(result.data or {}).get("topic"),
                )
                await self._update_command_status(
                    command_id,
                    CommandStatus.EXECUTING,
                    result={"dispatched_at": datetime.utcnow().isoformat(), **(result.data or {})},
                )
            else:
                raise Exception(result.message)
        
        except Exception as e:
            # Check if we should retry
            command_info['retry_count'] += 1
            
            if command_info['retry_count'] < self._max_retries:
                logger.warning(
                    "command_retry",
                    command_id=command_id,
                    retry=command_info['retry_count'],
                    error=str(e)
                )
                # Re-queue with delay
                await asyncio.sleep(2 ** command_info['retry_count'])  # Exponential backoff
                self._pending_commands.pop(command_id, None)
                await self._command_queue.put(command_info)
            else:
                # Mark as failed
                await self._update_command_status(
                    command_id,
                    CommandStatus.FAILED,
                    result={'error': str(e), 'failed_at': datetime.utcnow().isoformat()}
                )
                
                if organization_id:
                    await self._broadcast_command_status(
                        organization_id, asset_id, command_id,
                        CommandStatus.FAILED, action_id,
                        error=str(e)
                    )
                
                logger.error(
                    "command_failed",
                    command_id=command_id,
                    asset_id=asset_id,
                    error=str(e)
                )
                self._pending_commands.pop(command_id, None)
    
    async def _send_to_edge_agent(
        self,
        command_id: str,
        asset_id: str,
        organization_id: Optional[str],
        action_id: str,
        parameters: Dict,
        timeout_seconds: int,
    ) -> CommandResult:
        """
        Send command to edge agent via Redpanda message broker.
        """
        try:
            # Check if producer is available
            if not self._producer:
                logger.warning("redpanda_producer_not_available", asset_id=asset_id)
                return CommandResult(
                    success=False,
                    message="Redpanda producer not available",
                    error_code="PRODUCER_UNAVAILABLE"
                )
            
            # Build command message
            command_message = {
                'schema_version': 1,
                'message_type': 'command',
                'command_id': command_id,
                'asset_id': asset_id,
                'organization_id': organization_id,
                'action_id': action_id,
                'parameters': parameters,
                'timeout_seconds': timeout_seconds,
                'timestamp': datetime.utcnow().isoformat(),
            }
            
            topic = settings.REDPANDA_COMMAND_TOPIC
            
            # Send to Redpanda
            await self._producer.send_and_wait(
                topic,
                command_message,
                key=command_id.encode("utf-8"),
            )
            
            logger.info(
                "command_sent_to_redpanda",
                command_id=command_id,
                asset_id=asset_id,
                action=action_id,
                topic=topic
            )
            
            return CommandResult(
                success=True,
                message="Command sent to edge agent via Redpanda",
                data={
                    'sent_at': datetime.utcnow().isoformat(),
                    'topic': topic,
                    'ack_topic': settings.REDPANDA_COMMAND_ACK_TOPIC,
                }
            )
        
        except Exception as e:
            logger.error(
                "redpanda_send_failed",
                command_id=command_id,
                asset_id=asset_id,
                action=action_id,
                error=str(e)
            )
            return CommandResult(
                success=False,
                message=f"Failed to send command: {str(e)}",
                error_code="SEND_FAILED"
            )

    async def handle_command_ack(self, ack_payload: Dict[str, Any]) -> bool:
        """Handle an edge-agent command acknowledgement payload."""
        command_id = str(ack_payload.get("command_id") or "")
        if not command_id:
            logger.warning("command_ack_missing_command_id", payload=ack_payload)
            return False

        command_info = self._pending_commands.get(command_id)
        if not command_info:
            logger.warning("command_ack_for_unknown_command", command_id=command_id)
            return False

        raw_status = str(ack_payload.get("status") or "").lower()
        success = bool(ack_payload.get("success"))
        if raw_status in {"completed", "success", "succeeded"}:
            success = True
        elif raw_status in {"failed", "error", "rejected"}:
            success = False

        now = datetime.utcnow().isoformat()
        result = {
            "ack_received_at": now,
            "edge_ack": ack_payload,
        }

        if success:
            result["completed_at"] = now
            status = CommandStatus.COMPLETED
            error = None
        else:
            result["failed_at"] = now
            status = CommandStatus.FAILED
            error = (
                ack_payload.get("error")
                or ack_payload.get("message")
                or "Edge agent reported command failure"
            )
            result["error"] = error

        await self._update_command_status(command_id, status, result=result)

        organization_id = command_info.get("organization_id")
        if organization_id:
            await self._broadcast_command_status(
                organization_id,
                command_info["asset_id"],
                command_id,
                status,
                command_info["action_id"],
                result=ack_payload if success else None,
                error=error,
            )

        self._pending_commands.pop(command_id, None)
        logger.info(
            "command_ack_handled",
            command_id=command_id,
            status=status.value,
        )
        return True

    async def _ack_consumer_loop(self):
        """Consume edge-agent command acknowledgements from Redpanda."""
        while self._running and self._ack_consumer is not None:
            try:
                async for message in self._ack_consumer:
                    payload = message.value
                    if isinstance(payload, bytes):
                        payload = json.loads(payload.decode("utf-8"))
                    if not isinstance(payload, dict):
                        logger.warning("command_ack_invalid_payload", payload=payload)
                        continue
                    await self.handle_command_ack(payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("command_ack_consumer_error", error=str(e))
                await asyncio.sleep(5)
    
    async def _update_command_status(
        self,
        command_id: str,
        status: CommandStatus,
        result: Optional[Dict] = None
    ):
        """Update command status in database"""
        async with AsyncSessionLocal() as session:
            update_data = {
                'status': status.value,
                'executed_at': datetime.utcnow() if status in [CommandStatus.EXECUTING, CommandStatus.COMPLETED] else None
            }
            
            if result:
                update_data['result'] = result
            
            await session.execute(
                update(Command)
                .where(Command.id == command_id)
                .values(**update_data)
            )
            await session.commit()
    
    async def _broadcast_command_status(
        self,
        organization_id: str,
        asset_id: str,
        command_id: str,
        status: CommandStatus,
        action: str,
        result: Optional[Dict] = None,
        error: Optional[str] = None
    ):
        """Broadcast command status update via WebSocket"""
        payload = {
            'command_id': command_id,
            'status': status.value,
            'action': action,
            'asset_id': asset_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        if result:
            payload['result'] = result
        if error:
            payload['error'] = error
        
        # Use the alarm publish method with command_status type
        await websocket_manager.publish_alarm(
            organization_id=organization_id,
            asset_id=asset_id,
            alarm_data={
                'type': 'command_status',
                'severity': 'info',
                'message': f"Command {action} {status.value}",
                'command_id': command_id,
                'status': status.value,
                'result': result,
                'error': error
            }
        )
    
    async def _timeout_monitor(self):
        """Monitor for timed out commands"""
        while self._running:
            try:
                now = datetime.utcnow()
                timed_out = []
                
                for command_id, command_info in self._pending_commands.items():
                    elapsed = (now - command_info['submitted_at']).total_seconds()
                    
                    if elapsed > command_info['timeout']:
                        timed_out.append(command_id)
                
                for command_id in timed_out:
                    await self._mark_command_timeout(command_id, now)
                
                await asyncio.sleep(10)  # Check every 10 seconds
            
            except Exception as e:
                logger.error("timeout_monitor_error", error=str(e))
                await asyncio.sleep(10)
    
    def get_pending_count(self) -> int:
        """Get count of pending commands"""
        return len(self._pending_commands)

    async def _mark_command_timeout(self, command_id: str, now: datetime):
        """Mark a pending command timed out and remove it from pending tracking."""
        command_info = self._pending_commands.pop(command_id, None)
        if not command_info:
            return

        await self._update_command_status(
            command_id,
            CommandStatus.TIMEOUT,
            result={'timeout_at': now.isoformat()}
        )

        organization_id = command_info.get("organization_id")
        if organization_id:
            await self._broadcast_command_status(
                organization_id,
                command_info["asset_id"],
                command_id,
                CommandStatus.TIMEOUT,
                command_info["action_id"],
                error="Command acknowledgement timed out",
            )

        logger.warning("command_timeout", command_id=command_id)


# Global instance
command_executor = CommandExecutor()
