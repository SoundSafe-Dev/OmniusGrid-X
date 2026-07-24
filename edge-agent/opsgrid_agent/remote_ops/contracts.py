"""Versioned action, parameter, result, and size contracts."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

REMOTE_OPERATION_SCHEMA_VERSION = 1
REMOTE_RESULT_MAX_BYTES = 64 * 1024
MAX_COMMAND_ACK_BYTES = 128 * 1024
MAX_REMOTE_LOG_ENTRIES = 200

AGENT_FETCH_LOGS = "agent_fetch_logs"
AGENT_DIAGNOSTICS = "agent_diagnostics"
COLLECTOR_RESTART = "collector_restart"
AGENT_EFFECTIVE_CONFIG = "agent_effective_config"

REMOTE_OPERATION_ACTIONS = frozenset(
    {
        AGENT_FETCH_LOGS,
        AGENT_DIAGNOSTICS,
        COLLECTOR_RESTART,
        AGENT_EFFECTIVE_CONFIG,
    }
)

_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PUBLIC_ERRORS = {
    "collector_not_found": "Collector is not configured on this agent",
    "collector_disabled": "Collector is disabled",
    "collector_restart_in_progress": "A collector restart is already in progress",
    "collector_restart_failed": "Collector did not become ready after restart",
    "invalid_parameters": "The operation parameters are invalid",
    "operation_failed": "The remote operation failed",
    "result_too_large": "The operation result exceeded its size limit",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _OperationParameters(_StrictModel):
    schema_version: Literal[1] = REMOTE_OPERATION_SCHEMA_VERSION


class _FetchLogsParameters(_OperationParameters):
    limit: int = Field(default=100, ge=1, le=MAX_REMOTE_LOG_ENTRIES)
    since: Optional[datetime] = None
    levels: list[
        Literal["debug", "info", "warning", "error", "critical"]
    ] = Field(default_factory=list, max_length=5)

    @field_validator("since")
    @classmethod
    def require_aware_since(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("since must include a timezone")
        return value


class _CollectorRestartParameters(_OperationParameters):
    collector_asset_id: str = Field(min_length=36, max_length=36)
    readiness_timeout_seconds: int = Field(default=10, ge=1, le=30)


class _EmptyParameters(_OperationParameters):
    pass


class _RemoteLogEntry(_StrictModel):
    timestamp: datetime
    level: Literal["debug", "info", "warning", "error", "critical"]
    event: str = Field(min_length=1, max_length=512)
    fields: dict[str, Any] = Field(default_factory=dict)


class _FetchLogsResult(_StrictModel):
    schema_version: Literal[1]
    action: Literal["agent_fetch_logs"]
    agent_id: str = Field(min_length=1, max_length=255)
    generated_at: datetime
    entries: list[_RemoteLogEntry] = Field(max_length=MAX_REMOTE_LOG_ENTRIES)
    returned_count: int = Field(ge=0, le=MAX_REMOTE_LOG_ENTRIES)
    available_count: int = Field(ge=0)
    truncated: bool
    redacted_fields: int = Field(ge=0)


class _DiagnosticsResult(_StrictModel):
    schema_version: Literal[1]
    action: Literal["agent_diagnostics"]
    agent_id: str = Field(min_length=1, max_length=255)
    generated_at: datetime
    overall_status: Literal["healthy", "degraded"]
    agent: dict[str, Any]
    buffer: dict[str, Any]
    transport: dict[str, Any]
    disk: dict[str, Any]
    clock: dict[str, Any]
    collectors: dict[str, Any]
    warnings: list[str] = Field(default_factory=list, max_length=20)
    truncated: bool = False


class _CollectorRestartResult(_StrictModel):
    schema_version: Literal[1]
    action: Literal["collector_restart"]
    agent_id: str = Field(min_length=1, max_length=255)
    generated_at: datetime
    collector_asset_id: str = Field(min_length=1, max_length=64)
    ready: bool
    duration_ms: int = Field(ge=0)
    before: dict[str, Any]
    after: dict[str, Any]


class _EffectiveConfigResult(_StrictModel):
    schema_version: Literal[1]
    action: Literal["agent_effective_config"]
    agent_id: str = Field(min_length=1, max_length=255)
    generated_at: datetime
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_config: dict[str, Any]
    redacted_fields: int = Field(ge=0)
    omitted_collectors: int = Field(ge=0)
    truncated: bool


_PARAMETER_MODELS: dict[str, type[_StrictModel]] = {
    AGENT_FETCH_LOGS: _FetchLogsParameters,
    AGENT_DIAGNOSTICS: _EmptyParameters,
    COLLECTOR_RESTART: _CollectorRestartParameters,
    AGENT_EFFECTIVE_CONFIG: _EmptyParameters,
}
_RESULT_MODELS: dict[str, type[_StrictModel]] = {
    AGENT_FETCH_LOGS: _FetchLogsResult,
    AGENT_DIAGNOSTICS: _DiagnosticsResult,
    COLLECTOR_RESTART: _CollectorRestartResult,
    AGENT_EFFECTIVE_CONFIG: _EffectiveConfigResult,
}


class RemoteOperationError(RuntimeError):
    """A stable public failure safe to return through the ack path."""

    def __init__(self, code: str, message: Optional[str] = None):
        self.code = code if _ERROR_CODE.fullmatch(code) else "operation_failed"
        self.public_message = (
            message
            or _PUBLIC_ERRORS.get(self.code)
            or _PUBLIC_ERRORS["operation_failed"]
        )[:256]
        super().__init__(self.public_message)


def is_remote_operation(action_id: str) -> bool:
    return action_id in REMOTE_OPERATION_ACTIONS


def validate_parameters(
    action_id: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    model = _PARAMETER_MODELS.get(action_id)
    if model is None:
        raise RemoteOperationError("invalid_parameters")
    try:
        return model.model_validate(parameters).model_dump(
            mode="json",
            exclude_none=True,
        )
    except Exception as exc:
        raise RemoteOperationError("invalid_parameters") from exc


def validate_result(
    action_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    model = _RESULT_MODELS.get(action_id)
    if model is None:
        raise RemoteOperationError("operation_failed")
    try:
        normalized = model.model_validate(result).model_dump(mode="json")
    except Exception as exc:
        raise RemoteOperationError("operation_failed") from exc
    if json_size(normalized) > REMOTE_RESULT_MAX_BYTES:
        raise RemoteOperationError("result_too_large")
    return normalized


def error_result(action_id: str, error: RemoteOperationError) -> dict[str, Any]:
    return {
        "schema_version": REMOTE_OPERATION_SCHEMA_VERSION,
        "action": action_id,
        "error_code": error.code,
        "message": error.public_message,
    }


def json_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )
