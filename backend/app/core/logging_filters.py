"""Logging filters for credentials carried in signed download URLs."""

from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_QUERY_PARAMETERS = frozenset({"token", "signature"})
REDACTED_VALUE = "[REDACTED]"


def redact_sensitive_query_parameters(target: str) -> str:
    """Return an HTTP target with signed-link credentials redacted."""
    parsed = urlsplit(target)
    if not parsed.query:
        return target
    changed = False
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_PARAMETERS:
            value = REDACTED_VALUE
            changed = True
        query.append((key, value))
    if not changed:
        return target
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


class SensitiveQueryAccessLogFilter(logging.Filter):
    """Redact capability credentials from Uvicorn's access-log arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = redact_sensitive_query_parameters(args[2])
                record.args = tuple(args)
        return True


def install_sensitive_query_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(item, SensitiveQueryAccessLogFilter) for item in logger.filters):
        return
    logger.addFilter(SensitiveQueryAccessLogFilter())
