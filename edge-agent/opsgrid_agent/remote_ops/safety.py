"""Recursive redaction and truncation for remotely returned agent data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REDACTED = "<redacted>"
TRUNCATED = "<truncated>"

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


@dataclass(frozen=True)
class Sanitized:
    value: Any
    redacted_fields: int
    truncated: bool


@dataclass
class _Budget:
    remaining_nodes: int
    redacted_fields: int = 0
    truncated: bool = False


def sanitize(
    value: Any,
    *,
    max_depth: int = 6,
    max_items: int = 50,
    max_string: int = 1024,
    max_nodes: int = 500,
) -> Sanitized:
    budget = _Budget(remaining_nodes=max_nodes)
    cleaned = _sanitize_value(
        value,
        budget=budget,
        depth=0,
        max_depth=max_depth,
        max_items=max_items,
        max_string=max_string,
    )
    return Sanitized(
        value=cleaned,
        redacted_fields=budget.redacted_fields,
        truncated=budget.truncated,
    )


def _sanitize_value(
    value: Any,
    *,
    budget: _Budget,
    depth: int,
    max_depth: int,
    max_items: int,
    max_string: int,
) -> Any:
    budget.remaining_nodes -= 1
    if budget.remaining_nodes < 0 or depth > max_depth:
        budget.truncated = True
        return TRUNCATED

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(value, budget, max_string)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        items = list(value.items())
        if len(items) > max_items:
            budget.truncated = True
            items = items[:max_items]
        for raw_key, child in items:
            key = str(raw_key)[:128]
            if _sensitive_key(key):
                output[key] = REDACTED
                budget.redacted_fields += 1
                continue
            output[key] = _sanitize_value(
                child,
                budget=budget,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_string=max_string,
            )
        return output
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        if len(items) > max_items:
            budget.truncated = True
            items = items[:max_items]
        return [
            _sanitize_value(
                child,
                budget=budget,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_string=max_string,
            )
            for child in items
        ]
    return _sanitize_string(str(value), budget, max_string)


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _sanitize_string(value: str, budget: _Budget, max_string: int) -> str:
    cleaned = _BEARER.sub("Bearer <redacted>", value)
    cleaned, inline_count = _INLINE_SECRET.subn(
        lambda match: f"{match.group(1)}={REDACTED}",
        cleaned,
    )
    budget.redacted_fields += inline_count
    if cleaned != value and inline_count == 0:
        budget.redacted_fields += 1

    if "://" in cleaned:
        try:
            parsed = urlsplit(cleaned)
            if parsed.username is not None or parsed.password is not None:
                hostname = parsed.hostname or ""
                if parsed.port is not None:
                    hostname = f"{hostname}:{parsed.port}"
                parsed = parsed._replace(netloc=hostname)
                budget.redacted_fields += 1
            if parsed.query:
                parsed = parsed._replace(query="redacted")
                budget.redacted_fields += 1
            cleaned = urlunsplit(parsed)
        except (TypeError, ValueError):
            pass

    if len(cleaned) > max_string:
        budget.truncated = True
        cleaned = f"{cleaned[:max_string]}…"
    return cleaned
