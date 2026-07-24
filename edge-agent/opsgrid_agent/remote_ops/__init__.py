"""Bounded remote edge-agent operations."""

from .contracts import (
    AGENT_DIAGNOSTICS,
    AGENT_EFFECTIVE_CONFIG,
    AGENT_FETCH_LOGS,
    COLLECTOR_RESTART,
    MAX_COMMAND_ACK_BYTES,
    REMOTE_OPERATION_ACTIONS,
    REMOTE_OPERATION_SCHEMA_VERSION,
    REMOTE_RESULT_MAX_BYTES,
    RemoteOperationError,
    error_result,
    is_remote_operation,
    validate_parameters,
    validate_result,
)
from .log_buffer import capture_structured_log, structured_log_buffer
from .service import AgentRemoteOperations

__all__ = [
    "AGENT_DIAGNOSTICS",
    "AGENT_EFFECTIVE_CONFIG",
    "AGENT_FETCH_LOGS",
    "COLLECTOR_RESTART",
    "MAX_COMMAND_ACK_BYTES",
    "REMOTE_OPERATION_ACTIONS",
    "REMOTE_OPERATION_SCHEMA_VERSION",
    "REMOTE_RESULT_MAX_BYTES",
    "AgentRemoteOperations",
    "RemoteOperationError",
    "capture_structured_log",
    "error_result",
    "is_remote_operation",
    "structured_log_buffer",
    "validate_parameters",
    "validate_result",
]
