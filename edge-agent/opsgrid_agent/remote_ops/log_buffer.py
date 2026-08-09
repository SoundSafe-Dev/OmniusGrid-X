"""Bounded in-memory structured-log capture for on-demand support."""

from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from .safety import sanitize

_LEVELS = {"debug", "info", "warning", "error", "critical"}


class StructuredLogBuffer:
    def __init__(self, capacity: int = 1000):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._entries: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def append(self, method_name: str, event_dict: dict[str, Any]) -> None:
        level = str(event_dict.get("level") or method_name).lower()
        if level == "warn":
            level = "warning"
        if level not in _LEVELS:
            level = "info"

        raw_event = event_dict.get("event") or "log_event"
        event = sanitize(str(raw_event), max_string=512, max_nodes=10)
        raw_fields = {
            key: value
            for key, value in event_dict.items()
            if key not in {"event", "level", "timestamp"}
        }
        fields = sanitize(
            raw_fields,
            max_depth=4,
            max_items=30,
            max_string=512,
            max_nodes=150,
        )
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event.value,
            "fields": fields.value,
            "_redacted_fields": (
                event.redacted_fields + fields.redacted_fields
            ),
            "_truncated": event.truncated or fields.truncated,
        }
        with self._lock:
            self._entries.append(entry)

    def fetch(
        self,
        *,
        limit: int,
        since: Optional[datetime],
        levels: set[str],
    ) -> tuple[list[dict[str, Any]], int, int, bool]:
        with self._lock:
            entries = [dict(entry) for entry in self._entries]

        filtered = []
        for entry in entries:
            if levels and entry["level"] not in levels:
                continue
            if since is not None:
                timestamp = datetime.fromisoformat(entry["timestamp"])
                if timestamp < since:
                    continue
            filtered.append(entry)

        available_count = len(filtered)
        selected = filtered[-limit:]
        redacted_fields = sum(
            int(entry.pop("_redacted_fields", 0))
            for entry in selected
        )
        content_truncated = any(
            bool(entry.pop("_truncated", False))
            for entry in selected
        )
        truncated = available_count > len(selected) or content_truncated
        return selected, available_count, redacted_fields, truncated


structured_log_buffer = StructuredLogBuffer(capacity=1000)


def capture_structured_log(
    _logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Structlog processor that captures a sanitized copy without mutation."""

    structured_log_buffer.append(method_name, event_dict)
    return event_dict
