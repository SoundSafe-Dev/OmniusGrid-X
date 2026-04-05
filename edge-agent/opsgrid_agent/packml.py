"""PackML State Machine Standardization (ISA-TR88.00.02)"""

from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


class PackMLState(str, Enum):
    """PackML standard states (ISA-TR88.00.02)"""
    IDLE = "Idle"
    STARTING = "Starting"
    EXECUTE = "Execute"
    COMPLETING = "Completing"
    COMPLETE = "Complete"
    RESETTING = "Resetting"
    HOLDING = "Holding"
    HELD = "Held"
    UNHOLDING = "Unholding"
    SUSPENDING = "Suspending"
    SUSPENDED = "Suspended"
    UNSUSPENDING = "Unsuspending"
    ABORTING = "Aborting"
    ABORTED = "Aborted"
    CLEARING = "Clearing"
    STOPPING = "Stopping"
    STOPPED = "Stopped"


# OEE-relevant state categories
PRODUCTIVE_STATES = {PackMLState.EXECUTE}
AVAILABILITY_LOSS_STATES = {
    PackMLState.IDLE, PackMLState.STARTING, PackMLState.COMPLETING,
    PackMLState.COMPLETE, PackMLState.RESETTING, PackMLState.HELD,
    PackMLState.HOLDING, PackMLState.UNHOLDING, PackMLState.SUSPENDED,
    PackMLState.SUSPENDING, PackMLState.UNSUSPENDING, PackMLState.ABORTED,
    PackMLState.ABORTING, PackMLState.CLEARING, PackMLState.STOPPED,
    PackMLState.STOPPING
}


@dataclass
class StateMapping:
    """Mapping configuration for vendor state → PackML state"""
    vendor_state: str
    packml_state: PackMLState
    confidence: float = 1.0
    metadata: Optional[Dict[str, Any]] = None


class PackMLStateMapper:
    """
    Maps vendor-specific equipment states to PackML standard states.
    
    Enables:
    - Unified OEE calculations across heterogeneous equipment
    - Standardized state transition analysis
    - Vendor-agnostic process behavior mapping
    """
    
    def __init__(self, mappings: Optional[Dict[str, str]] = None):
        """
        Initialize mapper with state mappings.
        
        Args:
            mappings: Dict mapping vendor states to PackML states
                     e.g., {"printing": "Execute", "heating": "Starting"}
        """
        self._mappings: Dict[str, PackMLState] = {}
        self._unknown_states: set = set()
        
        if mappings:
            self.load_mappings(mappings)
    
    def load_mappings(self, mappings: Dict[str, str]):
        """Load state mappings from configuration"""
        for vendor_state, packml_state_str in mappings.items():
            try:
                packml_state = PackMLState(packml_state_str)
                self._mappings[vendor_state.lower()] = packml_state
            except ValueError:
                logger.warning(
                    "invalid_packml_state",
                    vendor_state=vendor_state,
                    packml_state=packml_state_str
                )
        
        logger.info(
            "mappings_loaded",
            count=len(self._mappings)
        )
    
    def map_state(self, vendor_state: str) -> PackMLState:
        """
        Map a vendor-specific state to PackML state.
        
        Args:
            vendor_state: Raw state string from equipment
            
        Returns:
            PackMLState enum value
        """
        if not vendor_state:
            return PackMLState.IDLE
        
        # Normalize input
        normalized = vendor_state.lower().strip()
        
        # Direct mapping
        if normalized in self._mappings:
            return self._mappings[normalized]
        
        # Track unknown states
        if normalized not in self._unknown_states:
            self._unknown_states.add(normalized)
            logger.warning(
                "unknown_vendor_state",
                vendor_state=vendor_state,
                defaulting_to=PackMLState.IDLE
            )
        
        # Default to Idle with warning
        return PackMLState.IDLE
    
    def is_productive(self, state: PackMLState) -> bool:
        """Check if state counts as productive time for OEE"""
        return state in PRODUCTIVE_STATES
    
    def is_availability_loss(self, state: PackMLState) -> bool:
        """Check if state counts as availability loss"""
        return state in AVAILABILITY_LOSS_STATES
    
    def get_state_category(self, state: PackMLState) -> str:
        """Get OEE category for a state"""
        if self.is_productive(state):
            return "productive"
        elif self.is_availability_loss(state):
            return "availability_loss"
        else:
            return "unknown"
    
    def get_unknown_states(self) -> list:
        """Get list of vendor states that couldn't be mapped"""
        return list(self._unknown_states)


# Default mappings for common equipment types
DEFAULT_MAPPINGS = {
    # FDM 3D Printers (Bambu, QIDI, SOVOL, etc.)
    "3d_printer": {
        "printing": "Execute",
        "extruding": "Execute",
        "heating": "Starting",
        "bed_heating": "Starting",
        "nozzle_heating": "Starting",
        "homing": "Starting",
        "levelling": "Starting",
        "idle": "Idle",
        "ready": "Idle",
        "standby": "Idle",
        "paused": "Held",
        "pause": "Held",
        "error": "Aborted",
        "fault": "Aborted",
        "stopped": "Stopped",
        "complete": "Complete",
        "finished": "Complete",
        "cancelled": "Aborted",
        "maintaining": "Stopped",
    },
    
    # CNC Machines
    "cnc": {
        "running": "Execute",
        "cutting": "Execute",
        "machining": "Execute",
        "spindle_on": "Execute",
        "spindle_warmup": "Starting",
        "tool_change": "Held",
        "tool_changing": "Held",
        "homing": "Starting",
        "reference": "Starting",
        "idle": "Idle",
        "ready": "Idle",
        "alarm": "Aborted",
        "emergency_stop": "Aborted",
        "feed_hold": "Held",
        "door_open": "Held",
    },
    
    # Robotic Arms
    "robot": {
        "moving": "Execute",
        "executing": "Execute",
        "running_program": "Execute",
        "homing": "Starting",
        "calibrating": "Starting",
        "waiting": "Idle",
        "ready": "Idle",
        "idle": "Idle",
        "e_stopped": "Aborted",
        "emergency": "Aborted",
        "fault": "Aborted",
        "paused": "Held",
        "stopped": "Stopped",
    },
    
    # Generic manufacturing equipment
    "generic": {
        "running": "Execute",
        "active": "Execute",
        "working": "Execute",
        "processing": "Execute",
        "startup": "Starting",
        "initializing": "Starting",
        "ready": "Idle",
        "idle": "Idle",
        "standby": "Idle",
        "waiting": "Idle",
        "paused": "Held",
        "hold": "Held",
        "error": "Aborted",
        "fault": "Aborted",
        "alarm": "Aborted",
        "stopped": "Stopped",
        "off": "Stopped",
    }
}


def create_mapper_for_asset_type(asset_type: str, custom_mappings: Optional[Dict[str, str]] = None) -> PackMLStateMapper:
    """
    Create a PackML mapper for a specific asset type.
    
    Args:
        asset_type: Equipment category ('3d_printer', 'cnc', 'robot', etc.)
        custom_mappings: Additional vendor-specific mappings
        
    Returns:
        Configured PackMLStateMapper
    """
    # Start with default mappings for the asset type
    base_mappings = DEFAULT_MAPPINGS.get(asset_type, DEFAULT_MAPPINGS["generic"]).copy()
    
    # Merge custom mappings
    if custom_mappings:
        base_mappings.update(custom_mappings)
    
    return PackMLStateMapper(base_mappings)
