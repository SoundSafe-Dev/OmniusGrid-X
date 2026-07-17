"""
Immutable Audit Trail Service
Forensic logging of all commands for compliance
"""

import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal

logger = structlog.get_logger()


class ActorType(Enum):
    HUMAN = "human"
    AI_TACTICAL = "ai_tactical"
    AI_STRATEGIC = "ai_strategic"
    SYSTEM = "system"
    API = "api"


class CommandType(Enum):
    # Tactical commands (immediate)
    ADJUST_SPEED = "adjust_speed"
    ADJUST_TEMP = "adjust_temp"
    PAUSE_JOB = "pause_job"
    RESUME_JOB = "resume_job"
    EMERGENCY_STOP = "emergency_stop"
    
    # Strategic commands (planned)
    SCHEDULE_CHANGE = "schedule_change"
    MAINTENANCE_MODE = "maintenance_mode"
    PARAMETER_TUNING = "parameter_tuning"
    
    # Administrative
    COLLECTOR_RESTART = "collector_restart"
    MODEL_DEPLOY = "model_deploy"
    CERTIFICATE_REVOKE = "certificate_revoke"


@dataclass
class AuditEntry:
    """Immutable audit trail entry"""
    entry_id: str  # SHA256 hash for tamper detection
    timestamp: datetime
    actor_type: ActorType
    actor_id: str  # User ID, model version, or system component
    command_type: CommandType
    asset_id: str
    previous_state: Dict[str, Any]
    new_state: Dict[str, Any]
    command_parameters: Dict[str, Any]
    execution_result: str  # "success", "failed", "blocked"
    execution_error: Optional[str] = None
    ip_address: Optional[str] = None
    session_id: Optional[str] = None
    hash_chain: Optional[str] = None  # Link to previous entry for integrity


class AuditTrailService:
    """
    Immutable audit trail for all commands.
    Tamper-evident logging with hash chaining.
    """
    
    def __init__(self):
        self._last_hash: Optional[str] = None
    
    async def log_command(self,
                         actor_type: ActorType,
                         actor_id: str,
                         command_type: CommandType,
                         asset_id: str,
                         previous_state: Dict,
                         new_state: Dict,
                         parameters: Dict,
                         result: str = "success",
                         error: Optional[str] = None,
                         ip_address: Optional[str] = None,
                         session_id: Optional[str] = None) -> AuditEntry:
        """
        Log a command execution to the immutable audit trail.
        """
        # Generate timestamp
        timestamp = datetime.now(timezone.utc)
        
        # Build entry data for hashing
        entry_data = {
            'timestamp': timestamp.isoformat(),
            'actor_type': actor_type.value,
            'actor_id': actor_id,
            'command_type': command_type.value,
            'asset_id': asset_id,
            'previous_state': previous_state,
            'new_state': new_state,
            'parameters': parameters,
            'result': result,
            'error': error,
            'ip_address': ip_address,
            'session_id': session_id,
            'prev_hash': self._last_hash or 'genesis',
        }
        
        # Generate entry ID (SHA256 of entry data)
        entry_id = hashlib.sha256(
            json.dumps(entry_data, sort_keys=True).encode()
        ).hexdigest()
        
        # Create audit entry
        entry = AuditEntry(
            entry_id=entry_id,
            timestamp=timestamp,
            actor_type=actor_type,
            actor_id=actor_id,
            command_type=command_type,
            asset_id=asset_id,
            previous_state=previous_state,
            new_state=new_state,
            command_parameters=parameters,
            execution_result=result,
            execution_error=error,
            ip_address=ip_address,
            session_id=session_id,
            hash_chain=self._last_hash
        )
        
        # Persist to database
        await self._persist_entry(entry)
        
        # Update hash chain
        self._last_hash = entry_id
        
        # Log based on severity
        if result == "failed":
            logger.warning("command_failed",
                          entry_id=entry_id[:16],
                          asset_id=asset_id,
                          command=command_type.value,
                          actor=actor_id,
                          error=error)
        elif command_type == CommandType.EMERGENCY_STOP:
            logger.error("emergency_stop_executed",
                        entry_id=entry_id[:16],
                        asset_id=asset_id,
                        actor=actor_id)
        else:
            logger.info("command_logged",
                       entry_id=entry_id[:16],
                       asset_id=asset_id,
                       command=command_type.value,
                       actor=actor_id,
                       actor_type=actor_type.value)
        
        return entry
    
    async def _persist_entry(self, entry: AuditEntry):
        """Persist audit entry to database"""
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(f"""
                    INSERT INTO audit_trail (
                        entry_id,
                        timestamp,
                        actor_type,
                        actor_id,
                        command_type,
                        asset_id,
                        previous_state,
                        new_state,
                        command_parameters,
                        execution_result,
                        execution_error,
                        ip_address,
                        session_id,
                        hash_chain
                    ) VALUES (
                        '{entry.entry_id}',
                        '{entry.timestamp.isoformat()}',
                        '{entry.actor_type.value}',
                        '{entry.actor_id}',
                        '{entry.command_type.value}',
                        '{entry.asset_id}',
                        '{json.dumps(entry.previous_state)}',
                        '{json.dumps(entry.new_state)}',
                        '{json.dumps(entry.command_parameters)}',
                        '{entry.execution_result}',
                        {f"'{entry.execution_error}'" if entry.execution_error else 'NULL'},
                        {f"'{entry.ip_address}'" if entry.ip_address else 'NULL'},
                        {f"'{entry.session_id}'" if entry.session_id else 'NULL'},
                        {f"'{entry.hash_chain}'" if entry.hash_chain else 'NULL'}
                    )
                """)
            )
            await session.commit()
    
    async def query_audit_trail(self,
                               asset_id: Optional[str] = None,
                               actor_id: Optional[str] = None,
                               command_type: Optional[CommandType] = None,
                               start_time: Optional[datetime] = None,
                               end_time: Optional[datetime] = None,
                               limit: int = 100) -> List[AuditEntry]:
        """Query audit trail with filters"""
        
        conditions = []
        if asset_id:
            conditions.append(f"asset_id = '{asset_id}'")
        if actor_id:
            conditions.append(f"actor_id = '{actor_id}'")
        if command_type:
            conditions.append(f"command_type = '{command_type.value}'")
        if start_time:
            conditions.append(f"timestamp >= '{start_time.isoformat()}'")
        if end_time:
            conditions.append(f"timestamp <= '{end_time.isoformat()}'")
        
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text(f"""
                    SELECT entry_id, timestamp, actor_type, actor_id,
                           command_type, asset_id, previous_state, new_state,
                           command_parameters, execution_result, execution_error,
                           ip_address, session_id, hash_chain
                    FROM audit_trail
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                    LIMIT {limit}
                """)
            )
            
            entries = []
            for row in result:
                entries.append(AuditEntry(
                    entry_id=row[0],
                    timestamp=row[1],
                    actor_type=ActorType(row[2]),
                    actor_id=row[3],
                    command_type=CommandType(row[4]),
                    asset_id=row[5],
                    previous_state=json.loads(row[6]),
                    new_state=json.loads(row[7]),
                    command_parameters=json.loads(row[8]),
                    execution_result=row[9],
                    execution_error=row[10],
                    ip_address=row[11],
                    session_id=row[12],
                    hash_chain=row[13]
                ))
            
            return entries
    
    async def verify_integrity(self, 
                              start_time: Optional[datetime] = None,
                              end_time: Optional[datetime] = None) -> Dict:
        """
        Verify integrity of audit trail.
        Detects tampering by re-computing hashes and checking chain.
        """
        entries = await self.query_audit_trail(
            start_time=start_time,
            end_time=end_time,
            limit=10000
        )
        
        violations = []
        previous_hash = None
        
        for entry in sorted(entries, key=lambda e: e.timestamp):
            # Re-compute entry hash
            entry_data = {
                'timestamp': entry.timestamp.isoformat(),
                'actor_type': entry.actor_type.value,
                'actor_id': entry.actor_id,
                'command_type': entry.command_type.value,
                'asset_id': entry.asset_id,
                'previous_state': entry.previous_state,
                'new_state': entry.new_state,
                'parameters': entry.command_parameters,
                'result': entry.execution_result,
                'error': entry.execution_error,
                'ip_address': entry.ip_address,
                'session_id': entry.session_id,
                'prev_hash': entry.hash_chain or 'genesis',
            }
            
            computed_hash = hashlib.sha256(
                json.dumps(entry_data, sort_keys=True).encode()
            ).hexdigest()
            
            # Verify entry ID matches computed hash
            if computed_hash != entry.entry_id:
                violations.append({
                    'entry_id': entry.entry_id,
                    'violation': 'hash_mismatch',
                    'computed': computed_hash,
                    'stored': entry.entry_id
                })
            
            # Verify hash chain
            if entry.hash_chain and entry.hash_chain != previous_hash:
                violations.append({
                    'entry_id': entry.entry_id,
                    'violation': 'chain_broken',
                    'expected_previous': previous_hash,
                    'actual_previous': entry.hash_chain
                })
            
            previous_hash = entry.entry_id
        
        return {
            'total_entries_checked': len(entries),
            'violations_found': len(violations),
            'violations': violations,
            'integrity_verified': len(violations) == 0
        }
    
    async def export_for_compliance(self,
                                   start_time: datetime,
                                   end_time: datetime,
                                   asset_ids: Optional[List[str]] = None) -> Dict:
        """
        Export audit trail for compliance reporting.
        Includes integrity verification certificate.
        """
        entries = await self.query_audit_trail(
            start_time=start_time,
            end_time=end_time,
            limit=100000
        )
        
        if asset_ids:
            entries = [e for e in entries if e.asset_id in asset_ids]
        
        # Verify integrity
        integrity = await self.verify_integrity(start_time, end_time)
        
        export = {
            'export_metadata': {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'date_range': {
                    'start': start_time.isoformat(),
                    'end': end_time.isoformat()
                },
                'asset_filter': asset_ids,
                'entry_count': len(entries),
            },
            'integrity_certificate': integrity,
            'entries': [
                {
                    'entry_id': e.entry_id,
                    'timestamp': e.timestamp.isoformat(),
                    'actor_type': e.actor_type.value,
                    'actor_id': e.actor_id,
                    'command_type': e.command_type.value,
                    'asset_id': e.asset_id,
                    'previous_state': e.previous_state,
                    'new_state': e.new_state,
                    'parameters': e.command_parameters,
                    'result': e.execution_result,
                    'error': e.execution_error,
                    'ip_address': e.ip_address,
                }
                for e in entries
            ]
        }
        
        return export


# Global instance
audit_trail = AuditTrailService()
