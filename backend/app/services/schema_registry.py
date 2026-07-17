"""
Schema Registry and Data Contract Validation
Prevents silent data corruption from firmware updates
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field
from enum import Enum
import structlog
from pydantic import BaseModel, ConfigDict, ValidationError

logger = structlog.get_logger()


class SchemaViolationSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class SchemaViolation:
    """Record of a schema violation"""
    asset_id: str
    collector_type: str
    violation_type: str
    expected_schema_version: str
    received_payload: Dict
    error_message: str
    severity: SchemaViolationSeverity
    timestamp: datetime = field(default_factory=datetime.utcnow)


class DataContract(BaseModel):
    """
    Strict data contract for collector payloads.
    Uses Pydantic with extra="forbid" to catch schema drift.
    """
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class BambuLabsContract(DataContract):
    """Strict contract for Bambu Labs MQTT payloads"""
    nozzle_temp: float
    bed_temp: float
    chamber_temp: Optional[float] = None
    print_speed: Optional[float] = None
    progress_percent: Optional[float] = None
    layer_number: Optional[int] = None
    total_layers: Optional[int] = None
    state: str
    timestamp: datetime


class QidiContract(DataContract):
    """Strict contract for QIDI printers"""
    extruder_temperature_c: float  # Schema evolved from nozzle_temp
    bed_temperature_c: float
    print_progress: float
    current_status: str
    timestamp: datetime


class OrcaSlicerContract(DataContract):
    """Strict contract for ORCA Slicer file outputs"""
    layer_height: float
    print_time_seconds: int
    filament_used_mm: float
    total_layers: int
    estimated_weight_g: float


class SchemaRegistry:
    """
    Central schema registry for all collector types.
    Manages data contracts and handles schema evolution.
    """
    
    def __init__(self):
        self._contracts: Dict[str, type] = {
            'bambu_labs': BambuLabsContract,
            'qidi': QidiContract,
            'orca_slicer': OrcaSlicerContract,
        }
        
        self._schema_versions: Dict[str, str] = {
            'bambu_labs': '1.0',
            'qidi': '2.0',  # Updated after firmware change
            'orca_slicer': '1.0',
        }
        
        self._violations: List[SchemaViolation] = []
        self._quarantine_queue: List[Dict] = []
        self._max_violations = 10000
    
    def register_contract(self, collector_type: str, 
                         contract_class: type,
                         version: str):
        """Register a new data contract"""
        self._contracts[collector_type] = contract_class
        self._schema_versions[collector_type] = version
        logger.info("contract_registered", 
                   collector=collector_type,
                   version=version)
    
    def validate_payload(self, 
                         collector_type: str,
                         asset_id: str,
                         payload: Dict) -> Optional[Any]:
        """
        Validate payload against registered contract.
        
        Returns validated object on success.
        Returns None on failure (violation recorded, payload quarantined).
        """
        contract_class = self._contracts.get(collector_type)
        
        if not contract_class:
            # Unknown collector type - critical violation
            violation = SchemaViolation(
                asset_id=asset_id,
                collector_type=collector_type,
                violation_type="unknown_collector",
                expected_schema_version="unknown",
                received_payload=payload,
                error_message=f"No contract registered for collector type: {collector_type}",
                severity=SchemaViolationSeverity.CRITICAL
            )
            self._record_violation(violation)
            self._quarantine_payload(payload, violation)
            return None
        
        try:
            # Attempt strict validation
            validated = contract_class(**payload)
            return validated
            
        except ValidationError as e:
            # Schema violation detected
            error_msg = str(e)
            
            # Determine severity based on error type
            severity = self._determine_severity(e)
            
            violation = SchemaViolation(
                asset_id=asset_id,
                collector_type=collector_type,
                violation_type="schema_mismatch",
                expected_schema_version=self._schema_versions.get(collector_type, "unknown"),
                received_payload=payload,
                error_message=error_msg,
                severity=severity
            )
            
            self._record_violation(violation)
            self._quarantine_payload(payload, violation)
            
            logger.warning("schema_violation",
                        asset_id=asset_id,
                        collector=collector_type,
                        error=error_msg[:200])
            
            return None
        
        except Exception as e:
            # Unexpected error
            violation = SchemaViolation(
                asset_id=asset_id,
                collector_type=collector_type,
                violation_type="validation_error",
                expected_schema_version=self._schema_versions.get(collector_type, "unknown"),
                received_payload=payload,
                error_message=str(e),
                severity=SchemaViolationSeverity.CRITICAL
            )
            self._record_violation(violation)
            self._quarantine_payload(payload, violation)
            return None
    
    def _determine_severity(self, error: ValidationError) -> SchemaViolationSeverity:
        """Determine severity of validation error"""
        errors = error.errors()
        
        # Check for missing required fields
        missing_required = any(
            e.get('type') == 'value_error.missing' 
            for e in errors
        )
        
        # Check for extra fields (schema drift)
        extra_fields = any(
            e.get('type') == 'value_error.extra' 
            for e in errors
        )
        
        if missing_required:
            return SchemaViolationSeverity.CRITICAL
        elif extra_fields:
            return SchemaViolationSeverity.WARNING
        else:
            return SchemaViolationSeverity.WARNING
    
    def _record_violation(self, violation: SchemaViolation):
        """Record violation for alerting and analysis"""
        self._violations.append(violation)
        
        # Trim if exceeds max
        if len(self._violations) > self._max_violations:
            self._violations = self._violations[-self._max_violations:]
        
        # Critical violations trigger immediate alert
        if violation.severity == SchemaViolationSeverity.CRITICAL:
            self._alert_critical_violation(violation)
    
    def _alert_critical_violation(self, violation: SchemaViolation):
        """Alert engineers to critical schema violation"""
        logger.error("CRITICAL_SCHEMA_VIOLATION",
                    asset_id=violation.asset_id,
                    collector=violation.collector_type,
                    error=violation.error_message)
        
        # Could integrate with PagerDuty/Slack alerting here
    
    def _quarantine_payload(self, payload: Dict, violation: SchemaViolation):
        """Quarantine invalid payload for engineer review"""
        quarantine_record = {
            'payload': payload,
            'violation': {
                'asset_id': violation.asset_id,
                'collector_type': violation.collector_type,
                'violation_type': violation.violation_type,
                'expected_version': violation.expected_schema_version,
                'error_message': violation.error_message,
                'severity': violation.severity.value,
                'timestamp': violation.timestamp.isoformat(),
            },
            '_quarantined_at': datetime.now(timezone.utc).isoformat(),
        }
        
        self._quarantine_queue.append(quarantine_record)
        
        # Persist to dead letter queue (SQLite or file)
        asyncio.create_task(self._persist_to_dlq(quarantine_record))
    
    async def _persist_to_dlq(self, record: Dict):
        """Persist quarantined record to dead letter queue"""
        from app.services.cloud_gateway import cloud_gateway
        
        # Send to DLQ topic for cloud analysis
        await cloud_gateway.queue_discrete_event(
            'schema_violation_dlq',
            record
        )
    
    def get_violations(self, 
                       asset_id: Optional[str] = None,
                       collector_type: Optional[str] = None,
                       since: Optional[datetime] = None) -> List[SchemaViolation]:
        """Query recorded violations"""
        violations = self._violations
        
        if asset_id:
            violations = [v for v in violations if v.asset_id == asset_id]
        
        if collector_type:
            violations = [v for v in violations if v.collector_type == collector_type]
        
        if since:
            violations = [v for v in violations if v.timestamp >= since]
        
        return violations
    
    def get_quarantined_payloads(self) -> List[Dict]:
        """Get all quarantined payloads for review"""
        return self._quarantine_queue
    
    def clear_quarantine(self, before: Optional[datetime] = None):
        """Clear quarantined payloads after review"""
        if before:
            self._quarantine_queue = [
                p for p in self._quarantine_queue
                if datetime.fromisoformat(p['_quarantined_at']) > before
            ]
        else:
            self._quarantine_queue = []
    
    def get_schema_versions(self) -> Dict[str, str]:
        """Get current schema versions for all collectors"""
        return self._schema_versions.copy()


# Global registry instance
import asyncio
schema_registry = SchemaRegistry()
