"""Contracts and audit helpers for bounded remote edge-agent operations."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional
from urllib.parse import urlsplit, urlunsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Command

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
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "authorization",
    "credential",
    "privatekey",
    "signingkey",
    "accesscode",
    "connectionstring",
    "cookie",
)
_INLINE_SECRET = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SAFE_ERROR_MESSAGES = {
    "collector_not_found": "Collector is not configured on this agent",
    "collector_disabled": "Collector is disabled",
    "collector_restart_in_progress": "A collector restart is already in progress",
    "collector_restart_failed": "Collector did not become ready after restart",
    "invalid_parameters": "The edge agent rejected the operation parameters",
    "invalid_result": "The edge agent returned an invalid operation result",
    "operation_failed": "The remote operation failed",
    "result_too_large": "The remote operation result exceeded its size limit",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RemoteOperationRequest(_StrictModel):
    schema_version: Literal[1] = REMOTE_OPERATION_SCHEMA_VERSION


class FetchLogsRequest(RemoteOperationRequest):
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


class DiagnosticsRequest(RemoteOperationRequest):
    pass


class CollectorRestartRequest(RemoteOperationRequest):
    readiness_timeout_seconds: int = Field(default=10, ge=1, le=30)


class CollectorRestartParameters(CollectorRestartRequest):
    collector_asset_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
        ),
    )


class EffectiveConfigRequest(RemoteOperationRequest):
    pass


class RemoteLogEntry(_StrictModel):
    timestamp: datetime
    level: Literal["debug", "info", "warning", "error", "critical"]
    event: str = Field(min_length=1, max_length=512)
    fields: dict[str, Any] = Field(default_factory=dict)


class FetchLogsResult(_StrictModel):
    schema_version: Literal[1]
    action: Literal["agent_fetch_logs"]
    agent_id: str = Field(min_length=1, max_length=255)
    generated_at: datetime
    entries: list[RemoteLogEntry] = Field(max_length=MAX_REMOTE_LOG_ENTRIES)
    returned_count: int = Field(ge=0, le=MAX_REMOTE_LOG_ENTRIES)
    available_count: int = Field(ge=0)
    truncated: bool
    redacted_fields: int = Field(ge=0)


class DiagnosticsResult(_StrictModel):
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


class CollectorRestartResult(_StrictModel):
    schema_version: Literal[1]
    action: Literal["collector_restart"]
    agent_id: str = Field(min_length=1, max_length=255)
    generated_at: datetime
    collector_asset_id: str = Field(min_length=1, max_length=64)
    ready: bool
    duration_ms: int = Field(ge=0)
    before: dict[str, Any]
    after: dict[str, Any]


class EffectiveConfigResult(_StrictModel):
    schema_version: Literal[1]
    action: Literal["agent_effective_config"]
    agent_id: str = Field(min_length=1, max_length=255)
    generated_at: datetime
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_config: dict[str, Any]
    redacted_fields: int = Field(ge=0)
    omitted_collectors: int = Field(ge=0)
    truncated: bool


class RemoteOperationErrorResult(_StrictModel):
    schema_version: Literal[1]
    action: str = Field(min_length=1, max_length=64)
    error_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    message: str = Field(min_length=1, max_length=256)


_PARAMETER_MODELS: dict[str, type[RemoteOperationRequest]] = {
    AGENT_FETCH_LOGS: FetchLogsRequest,
    AGENT_DIAGNOSTICS: DiagnosticsRequest,
    COLLECTOR_RESTART: CollectorRestartParameters,
    AGENT_EFFECTIVE_CONFIG: EffectiveConfigRequest,
}

_RESULT_MODELS: dict[str, type[_StrictModel]] = {
    AGENT_FETCH_LOGS: FetchLogsResult,
    AGENT_DIAGNOSTICS: DiagnosticsResult,
    COLLECTOR_RESTART: CollectorRestartResult,
    AGENT_EFFECTIVE_CONFIG: EffectiveConfigResult,
}


class RemoteOperationContractError(ValueError):
    """Raised when a remote operation violates its versioned contract."""


@dataclass(frozen=True)
class RemoteOperationAuditContext:
    """Safe request metadata persisted beside a newly-created command."""

    ip_address: Optional[str]
    user_agent: Optional[str]
    target_agent_id: str


def is_remote_operation(action_id: str) -> bool:
    return action_id in REMOTE_OPERATION_ACTIONS


def normalize_remote_parameters(
    action_id: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    model = _PARAMETER_MODELS.get(action_id)
    if model is None:
        raise RemoteOperationContractError("Unsupported remote operation")
    try:
        return model.model_validate(parameters).model_dump(
            mode="json",
            exclude_none=True,
        )
    except Exception as exc:
        raise RemoteOperationContractError("Invalid operation parameters") from exc


def validate_remote_result(
    action_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    model = _RESULT_MODELS.get(action_id)
    if model is None:
        raise RemoteOperationContractError("Unsupported remote operation")
    cleaned, additional_redactions = _sanitize_remote_value(result)
    if (
        action_id in {AGENT_FETCH_LOGS, AGENT_EFFECTIVE_CONFIG}
        and isinstance(cleaned, dict)
    ):
        existing = cleaned.get("redacted_fields")
        cleaned["redacted_fields"] = (
            int(existing) if isinstance(existing, int) else 0
        ) + additional_redactions
    try:
        normalized = model.model_validate(cleaned).model_dump(mode="json")
    except Exception as exc:
        raise RemoteOperationContractError("Invalid operation result") from exc
    if _json_size(normalized) > REMOTE_RESULT_MAX_BYTES:
        raise RemoteOperationContractError("Operation result exceeds size limit")
    return normalized


def normalize_remote_ack(
    action_id: str,
    ack_payload: dict[str, Any],
    *,
    successful: bool,
) -> tuple[dict[str, Any], Optional[str]]:
    """Return a bounded ack safe for database and WebSocket persistence."""

    safe_ack = {
        key: ack_payload[key]
        for key in (
            "command_id",
            "agent_id",
            "asset_id",
            "organization_id",
            "status",
            "success",
            "timestamp",
        )
        if key in ack_payload
    }
    if successful:
        result = ack_payload.get("result")
        if not isinstance(result, dict):
            raise RemoteOperationContractError("Operation result must be an object")
        safe_ack["result"] = validate_remote_result(action_id, result)
        if _json_size(safe_ack) > MAX_COMMAND_ACK_BYTES:
            raise RemoteOperationContractError("Operation ack exceeds size limit")
        return safe_ack, None

    raw_result = ack_payload.get("result")
    error_code = (
        raw_result.get("error_code")
        if isinstance(raw_result, dict)
        else None
    )
    if not isinstance(error_code, str) or not _ERROR_CODE.fullmatch(error_code):
        error_code = "operation_failed"
    message = _SAFE_ERROR_MESSAGES.get(error_code, _SAFE_ERROR_MESSAGES["operation_failed"])
    safe_result = RemoteOperationErrorResult(
        schema_version=REMOTE_OPERATION_SCHEMA_VERSION,
        action=action_id,
        error_code=error_code,
        message=message,
    ).model_dump(mode="json")
    safe_ack["result"] = safe_result
    safe_ack["error"] = message
    return safe_ack, message


def invalid_remote_ack(
    action_id: str,
    ack_payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    safe_ack = {
        key: ack_payload[key]
        for key in (
            "command_id",
            "agent_id",
            "asset_id",
            "organization_id",
            "timestamp",
        )
        if key in ack_payload
    }
    message = _SAFE_ERROR_MESSAGES["invalid_result"]
    safe_ack.update(
        {
            "status": "failed",
            "success": False,
            "result": {
                "schema_version": REMOTE_OPERATION_SCHEMA_VERSION,
                "action": action_id,
                "error_code": "invalid_result",
                "message": message,
            },
            "error": message,
        }
    )
    return safe_ack, message


def remote_result_from_command(command_payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Extract the typed edge result from a durable command status payload."""

    if command_payload.get("status") not in {"completed", "failed", "timeout", "cancelled"}:
        return None
    stored = command_payload.get("result")
    if not isinstance(stored, dict):
        return None
    edge_ack = stored.get("edge_ack")
    if not isinstance(edge_ack, dict):
        return None
    result = edge_ack.get("result")
    return result if isinstance(result, dict) else None


def add_remote_requested_audit(
    db: AsyncSession,
    command: Command,
    context: RemoteOperationAuditContext,
) -> None:
    details = {
        "phase": "requested",
        "status": "requested",
        "command_id": str(command.id),
        "action": command.action_id,
        "target_asset_id": str(command.asset_id),
        "target_agent_id": context.target_agent_id,
        "parameters": _safe_parameter_summary(
            command.action_id,
            dict(command.parameters or {}),
        ),
    }
    db.add(
        AuditLog(
            user_id=command.issued_by,
            organization_id=command.organization_id,
            action="remote_agent_operation_requested",
            resource_type="remote_agent_command",
            resource_id=str(command.id),
            details=details,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            hash_chain="pending",
        )
    )


def add_remote_terminal_audit(
    db: AsyncSession,
    command: Command,
    *,
    status: str,
    occurred_at: datetime,
) -> None:
    """Append one terminal audit row without copying command result content."""

    if not is_remote_operation(command.action_id):
        return
    succeeded = status == "completed"
    db.add(
        AuditLog(
            user_id=command.issued_by,
            organization_id=command.organization_id,
            action=(
                "remote_agent_operation_completed"
                if succeeded
                else "remote_agent_operation_failed"
            ),
            resource_type="remote_agent_command",
            resource_id=str(command.id),
            details={
                "phase": "terminal",
                "status": status,
                "command_id": str(command.id),
                "action": command.action_id,
                "target_asset_id": str(command.asset_id),
                "occurred_at": occurred_at.isoformat(),
            },
            hash_chain="pending",
        )
    )


def _safe_parameter_summary(
    action_id: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    if action_id == AGENT_FETCH_LOGS:
        return {
            key: parameters[key]
            for key in ("schema_version", "limit", "since", "levels")
            if key in parameters
        }
    if action_id == COLLECTOR_RESTART:
        return {
            key: parameters[key]
            for key in (
                "schema_version",
                "collector_asset_id",
                "readiness_timeout_seconds",
            )
            if key in parameters
        }
    return {"schema_version": parameters.get("schema_version", 1)}


def _json_size(value: Any) -> int:
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _sanitize_remote_value(
    value: Any,
    *,
    depth: int = 0,
    budget: Optional[list[int]] = None,
) -> tuple[Any, int]:
    """Redact again at the trust boundary before persistence."""

    if budget is None:
        budget = [1000]
    budget[0] -= 1
    if budget[0] < 0 or depth > 6:
        return "<truncated>", 0
    if value is None or isinstance(value, (bool, int, float)):
        return value, 0
    if isinstance(value, str):
        return _sanitize_remote_string(value)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        redactions = 0
        for raw_key, child in list(value.items())[:50]:
            key = str(raw_key)[:128]
            normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
            if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
                output[key] = "<redacted>"
                if child != "<redacted>":
                    redactions += 1
                continue
            cleaned, count = _sanitize_remote_value(
                child,
                depth=depth + 1,
                budget=budget,
            )
            output[key] = cleaned
            redactions += count
        return output, redactions
    if isinstance(value, (list, tuple)):
        output = []
        redactions = 0
        for child in list(value)[:50]:
            cleaned, count = _sanitize_remote_value(
                child,
                depth=depth + 1,
                budget=budget,
            )
            output.append(cleaned)
            redactions += count
        return output, redactions
    return _sanitize_remote_string(str(value))


def _sanitize_remote_string(value: str) -> tuple[str, int]:
    cleaned = _BEARER.sub("Bearer <redacted>", value)
    cleaned, inline_count = _INLINE_SECRET.subn(
        lambda match: f"{match.group(1)}=<redacted>",
        cleaned,
    )
    redactions = inline_count
    if cleaned != value and inline_count == 0:
        redactions += 1
    if "://" in cleaned:
        try:
            parsed = urlsplit(cleaned)
            if parsed.username is not None or parsed.password is not None:
                hostname = parsed.hostname or ""
                if parsed.port is not None:
                    hostname = f"{hostname}:{parsed.port}"
                parsed = parsed._replace(netloc=hostname)
                redactions += 1
            if parsed.query and parsed.query != "redacted":
                parsed = parsed._replace(query="redacted")
                redactions += 1
            cleaned = urlunsplit(parsed)
        except (TypeError, ValueError):
            pass
    if len(cleaned) > 2048:
        cleaned = f"{cleaned[:2048]}…"
    return cleaned, redactions
