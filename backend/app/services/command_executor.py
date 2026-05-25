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
from aiokafka import AIOKafkaProducer

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
        
        # Stop Redpanda producer
        if self._producer:
            try:
                await self._producer.stop()
                logger.info("redpanda_producer_stopped")
            except Exception as e:
                logger.error("redpanda_producer_stop_failed", error=str(e))
        
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
            
            # TODO: Send command to edge agent via Redpanda
            # For now, simulate execution
            result = await self._send_to_edge_agent(
                asset_id, action_id, parameters
            )
            
            if result.success:
                await self._update_command_status(
                    command_id,
                    CommandStatus.COMPLETED,
                    result={'completed_at': datetime.utcnow().isoformat(), **(result.data or {})}
                )
                
                if organization_id:
                    await self._broadcast_command_status(
                        organization_id, asset_id, command_id,
                        CommandStatus.COMPLETED, action_id,
                        result=result.data
                    )
                
                logger.info(
                    "command_completed",
                    command_id=command_id,
                    asset_id=asset_id
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
        
        finally:
            # Remove from pending
            if command_id in self._pending_commands:
                del self._pending_commands[command_id]
    
    async def _send_to_edge_agent(
        self,
        asset_id: str,
        action_id: str,
        parameters: Dict
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
                'asset_id': asset_id,
                'action_id': action_id,
                'parameters': parameters,
                'timestamp': datetime.utcnow().isoformat(),
                'message_type': 'command'
            }
            
            # Determine topic (use asset-specific topic or global command topic)
            topic = f"{settings.REDPANDA_TOPICS_PREFIX}.commands.{asset_id}"
            
            # Send to Redpanda
            await self._producer.send_and_wait(topic, command_message)
            
            logger.info(
                "command_sent_to_redpanda",
                asset_id=asset_id,
                action=action_id,
                topic=topic
            )
            
            return CommandResult(
                success=True,
                message="Command sent to edge agent via Redpanda",
                data={
                    'sent_at': datetime.utcnow().isoformat(),
                    'topic': topic
                }
            )
        
        except Exception as e:
            logger.error(
                "redpanda_send_failed",
                asset_id=asset_id,
                action=action_id,
                error=str(e)
            )
            return CommandResult(
                success=False,
                message=f"Failed to send command: {str(e)}",
                error_code="SEND_FAILED"
            )
    
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
                    await self._update_command_status(
                        command_id,
                        CommandStatus.TIMEOUT,
                        result={'timeout_at': now.isoformat()}
                    )
                    
                    if command_id in self._pending_commands:
                        del self._pending_commands[command_id]
                    
                    logger.warning("command_timeout", command_id=command_id)
                
                await asyncio.sleep(10)  # Check every 10 seconds
            
            except Exception as e:
                logger.error("timeout_monitor_error", error=str(e))
                await asyncio.sleep(10)
    
    def get_pending_count(self) -> int:
        """Get count of pending commands"""
        return len(self._pending_commands)


# Global instance
command_executor = CommandExecutor()
