"""Fixed remote-operation handlers; no shell or caller-selected file access."""

from __future__ import annotations

import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .contracts import (
    AGENT_DIAGNOSTICS,
    AGENT_EFFECTIVE_CONFIG,
    AGENT_FETCH_LOGS,
    COLLECTOR_RESTART,
    REMOTE_OPERATION_SCHEMA_VERSION,
    REMOTE_RESULT_MAX_BYTES,
    RemoteOperationError,
    json_size,
    validate_parameters,
    validate_result,
)
from .log_buffer import StructuredLogBuffer
from .safety import sanitize


class AgentRemoteOperations:
    """Own the four explicitly supported support operations."""

    def __init__(
        self,
        *,
        agent_id: str,
        config_provider: Callable[[], dict[str, Any]],
        manifest_provider: Callable[[], dict[str, Any]],
        config_hash_provider: Callable[[], str],
        buffer: Any,
        coordinator: Any,
        kafka_connected: Callable[[], bool],
        command_connected: Callable[[], bool],
        log_buffer: StructuredLogBuffer,
        started_monotonic: float,
    ):
        self.agent_id = str(agent_id)
        self._config_provider = config_provider
        self._manifest_provider = manifest_provider
        self._config_hash_provider = config_hash_provider
        self.buffer = buffer
        self.coordinator = coordinator
        self._kafka_connected = kafka_connected
        self._command_connected = command_connected
        self.log_buffer = log_buffer
        self.started_monotonic = started_monotonic

    def register(self, consumer: Any) -> None:
        consumer.register_handler(AGENT_FETCH_LOGS, self.fetch_logs)
        consumer.register_handler(AGENT_DIAGNOSTICS, self.diagnostics)
        consumer.register_handler(COLLECTOR_RESTART, self.restart_collector)
        consumer.register_handler(
            AGENT_EFFECTIVE_CONFIG,
            self.effective_config,
        )

    async def fetch_logs(self, command: dict[str, Any]) -> dict[str, Any]:
        parameters = validate_parameters(
            AGENT_FETCH_LOGS,
            command["parameters"],
        )
        since = (
            datetime.fromisoformat(parameters["since"])
            if parameters.get("since")
            else None
        )
        entries, available, redacted, truncated = self.log_buffer.fetch(
            limit=parameters["limit"],
            since=since,
            levels=set(parameters.get("levels") or []),
        )
        result = {
            "schema_version": REMOTE_OPERATION_SCHEMA_VERSION,
            "action": AGENT_FETCH_LOGS,
            "agent_id": self.agent_id,
            "generated_at": _utcnow(),
            "entries": entries,
            "returned_count": len(entries),
            "available_count": available,
            "truncated": truncated,
            "redacted_fields": redacted,
        }
        while entries and json_size(result) > REMOTE_RESULT_MAX_BYTES:
            entries.pop(0)
            result["returned_count"] = len(entries)
            result["truncated"] = True
        return validate_result(AGENT_FETCH_LOGS, result)

    async def diagnostics(self, command: dict[str, Any]) -> dict[str, Any]:
        validate_parameters(AGENT_DIAGNOSTICS, command["parameters"])
        warnings: list[str] = []
        try:
            buffer_stats = {
                "ok": True,
                "stats": await self.buffer.get_stats(),
            }
        except Exception:
            buffer_stats = {"ok": False, "error_code": "buffer_unavailable"}
            warnings.append("buffer_unavailable")

        config = self._config_provider()
        try:
            disk_root = Path(
                config.get("buffer_path", "/var/lib/opsgrid-agent/buffer.db")
            ).parent
            usage = shutil.disk_usage(disk_root)
            disk = {
                "ok": True,
                "total_bytes": usage.total,
                "free_bytes": usage.free,
                "used_percent": round(
                    ((usage.used / usage.total) * 100) if usage.total else 0,
                    2,
                ),
            }
        except Exception:
            disk = {"ok": False, "error_code": "disk_unavailable"}
            warnings.append("disk_unavailable")

        collectors, collector_truncated = self._bounded_collector_status()
        if collector_truncated:
            warnings.append("collector_status_truncated")
        manifest = self._manifest_provider()
        result = {
            "schema_version": REMOTE_OPERATION_SCHEMA_VERSION,
            "action": AGENT_DIAGNOSTICS,
            "agent_id": self.agent_id,
            "generated_at": _utcnow(),
            "overall_status": "degraded" if warnings else "healthy",
            "agent": {
                "version": manifest.get("agent_version"),
                "build_id": manifest.get("build_id"),
                "git_sha": manifest.get("git_sha"),
                "build_time": manifest.get("build_time"),
                "config_hash": self._config_hash_provider(),
                "uptime_seconds": round(
                    max(0.0, time.monotonic() - self.started_monotonic),
                    3,
                ),
            },
            "buffer": buffer_stats,
            "transport": {
                "kafka_connected": bool(self._kafka_connected()),
                "command_connected": bool(self._command_connected()),
            },
            "disk": disk,
            "clock": {
                "utc": _utcnow(),
                "monotonic_seconds": round(time.monotonic(), 3),
            },
            "collectors": collectors,
            "warnings": warnings,
            "truncated": collector_truncated,
        }
        return validate_result(AGENT_DIAGNOSTICS, result)

    async def restart_collector(
        self,
        command: dict[str, Any],
    ) -> dict[str, Any]:
        parameters = validate_parameters(
            COLLECTOR_RESTART,
            command["parameters"],
        )
        collector_asset_id = parameters["collector_asset_id"]
        if str(command.get("asset_id")) != collector_asset_id:
            raise RemoteOperationError("invalid_parameters")

        started = time.monotonic()
        try:
            outcome = await self.coordinator.restart_collector(
                collector_asset_id,
                readiness_timeout_seconds=parameters[
                    "readiness_timeout_seconds"
                ],
            )
        except KeyError as exc:
            raise RemoteOperationError("collector_not_found") from exc
        except PermissionError as exc:
            raise RemoteOperationError("collector_disabled") from exc
        except RuntimeError as exc:
            raise RemoteOperationError("collector_restart_failed") from exc

        result = {
            "schema_version": REMOTE_OPERATION_SCHEMA_VERSION,
            "action": COLLECTOR_RESTART,
            "agent_id": self.agent_id,
            "generated_at": _utcnow(),
            "collector_asset_id": collector_asset_id,
            "ready": True,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "before": outcome["before"],
            "after": outcome["after"],
        }
        return validate_result(COLLECTOR_RESTART, result)

    async def effective_config(
        self,
        command: dict[str, Any],
    ) -> dict[str, Any]:
        validate_parameters(AGENT_EFFECTIVE_CONFIG, command["parameters"])
        config = self._config_provider()
        raw_collectors = list(config.get("collectors") or [])
        safe_collectors: list[dict[str, Any]] = []
        redacted_fields = 0
        content_truncated = False

        for raw_collector in raw_collectors:
            cleaned = sanitize(
                raw_collector,
                max_depth=5,
                max_items=40,
                max_string=512,
                max_nodes=250,
            )
            candidate = (
                cleaned.value
                if isinstance(cleaned.value, dict)
                else {"value": cleaned.value}
            )
            tentative = safe_collectors + [candidate]
            if json_size(tentative) > REMOTE_RESULT_MAX_BYTES - 4096:
                content_truncated = True
                break
            safe_collectors.append(candidate)
            redacted_fields += cleaned.redacted_fields
            content_truncated = content_truncated or cleaned.truncated

        omitted = len(raw_collectors) - len(safe_collectors)
        effective = {
            "agent": {
                "heartbeat_interval_seconds": config.get(
                    "heartbeat_interval_seconds"
                ),
                "buffer_retention_hours": config.get(
                    "buffer_retention_hours"
                ),
                "bootstrap_managed": bool(config.get("bootstrap_managed")),
            },
            "collectors": safe_collectors,
        }
        result = {
            "schema_version": REMOTE_OPERATION_SCHEMA_VERSION,
            "action": AGENT_EFFECTIVE_CONFIG,
            "agent_id": self.agent_id,
            "generated_at": _utcnow(),
            "config_hash": self._config_hash_provider(),
            "effective_config": effective,
            "redacted_fields": redacted_fields,
            "omitted_collectors": omitted,
            "truncated": content_truncated or omitted > 0,
        }
        return validate_result(AGENT_EFFECTIVE_CONFIG, result)

    def _bounded_collector_status(self) -> tuple[dict[str, Any], bool]:
        status = self.coordinator.get_status()
        collectors = status.get("collectors") or {}
        ordered = sorted(collectors.items(), key=lambda item: str(item[0]))
        selected = ordered[:100]
        truncated = len(ordered) > len(selected)
        return {
            "running": bool(status.get("running")),
            "total_collectors": int(status.get("total_collectors") or 0),
            "active_collectors": int(status.get("active_collectors") or 0),
            "collectors": dict(selected),
            "omitted_collectors": len(ordered) - len(selected),
        }, truncated


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
