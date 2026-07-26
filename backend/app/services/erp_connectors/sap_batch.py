"""Parser for OData `$batch` multipart/mixed responses (SAP).

WHAT THE OLD PARSER DID. It split the body on the boundary, then split each part on
``\\r\\n\\r\\n`` and took element **[1]** as the JSON payload. An `application/http`
part is not shaped that way — it is:

    <MIME headers>
    <blank line>
    HTTP/1.1 200 OK          <- element [1] starts HERE
    <HTTP headers>
    <blank line>
    <body>                   <- the JSON is actually element [2]

So it fed the HTTP status line and headers to ``json.loads``, which raised, and the
bare ``except`` logged a warning and moved on. Every part was silently discarded:
`$batch` returned an empty list while reporting success. The comment above it said
"simplified implementation — in production, use a proper multipart parser", which is
what this is.

Three further things the old one could not do, each of which loses data quietly:

* **Per-part status.** A batch returns 202 overall while individual operations fail
  with 400/404 inside it. Without reading each part's status line, a failed
  operation is indistinguishable from a successful one that returned no rows.
* **Changesets.** Write operations are wrapped in a nested `multipart/mixed`
  changeset with its OWN boundary. A single-level split walks straight past them.
* **The real boundary.** The response boundary is chosen by the SERVER and is
  usually not the one sent in the request.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

_CONTENT_TYPE_BOUNDARY = re.compile(r'boundary="?([^";,\s]+)"?', re.IGNORECASE)
_STATUS_LINE = re.compile(r"^HTTP/\d(?:\.\d)?\s+(\d{3})\s*(.*)$")


@dataclass
class BatchPart:
    """One operation's result inside a batch response."""

    status: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[Any] = None
    raw_body: str = ""
    content_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def extract_boundary(content_type: str) -> Optional[str]:
    """Pull the boundary out of a Content-Type header.

    The server picks the response boundary, so parsing with the boundary that was
    SENT will usually match nothing and yield zero parts — which looks exactly like
    an empty result set.
    """
    if not content_type:
        return None
    match = _CONTENT_TYPE_BOUNDARY.search(content_type)
    return match.group(1) if match else None


def _split_parts(body: str, boundary: str) -> List[str]:
    """Split a multipart body into its parts.

    Uses the delimiters literally (``--boundary`` / ``--boundary--``) rather than a
    naive ``str.split`` on the bare boundary, which also matches the boundary token
    wherever it appears inside a payload.
    """
    delimiter = f"--{boundary}"
    terminator = f"--{boundary}--"

    if terminator in body:
        body = body.split(terminator, 1)[0]

    chunks = body.split(delimiter)
    # The first chunk is the preamble before the opening delimiter.
    return [c for c in chunks[1:] if c.strip()]


def _split_headers_and_body(chunk: str) -> tuple[Dict[str, str], str]:
    """Separate a MIME section's headers from its body.

    Accepts LF as well as CRLF: the spec says CRLF, and real servers (and anything
    that has passed through a text-mode proxy or a test fixture) sometimes send LF.
    A CRLF-only parser silently produces zero parts against those.
    """
    normalized = chunk.replace("\r\n", "\n").lstrip("\n")
    if "\n\n" in normalized:
        head, _, body = normalized.partition("\n\n")
    else:
        head, body = normalized, ""

    headers: Dict[str, str] = {}
    for line in head.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
    return headers, body


def _parse_http_part(chunk: str) -> Optional[BatchPart]:
    """Parse one `application/http` part: MIME headers, then an HTTP response."""
    mime_headers, http_section = _split_headers_and_body(chunk)
    if not http_section.strip():
        return None

    http_headers, body_text = _split_headers_and_body(http_section)

    # The status line is the first line of the HTTP section, which
    # _split_headers_and_body has already put into `http_headers` keys only if it
    # contained a colon — so read it from the raw text instead.
    first_line = http_section.replace("\r\n", "\n").lstrip("\n").split("\n", 1)[0].strip()
    match = _STATUS_LINE.match(first_line)
    if not match:
        return None
    status = int(match.group(1))

    parsed: Optional[Any] = None
    stripped = body_text.strip()
    if stripped:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            # Kept as raw text rather than discarded: an OData error body is often
            # XML, and throwing it away is how a failed operation becomes invisible.
            parsed = None

    return BatchPart(
        status=status,
        headers=http_headers,
        body=parsed,
        raw_body=stripped,
        content_id=mime_headers.get("content-id"),
    )


def parse_batch_response(body: str, boundary: str) -> List[BatchPart]:
    """Parse a `$batch` response into its parts, including nested changesets.

    Returns every part — successful AND failed — because the caller needs to know
    that operation 3 of 5 returned 400. Filtering to successes here is what made a
    partially-failed batch look like a smaller successful one.
    """
    parts: List[BatchPart] = []

    for chunk in _split_parts(body, boundary):
        mime_headers, _ = _split_headers_and_body(chunk)
        content_type = mime_headers.get("content-type", "")

        if content_type.startswith("multipart/mixed"):
            # A changeset: recurse with ITS boundary.
            nested = extract_boundary(content_type)
            if nested:
                _, nested_body = _split_headers_and_body(chunk)
                parts.extend(parse_batch_response(nested_body, nested))
            continue

        part = _parse_http_part(chunk)
        if part is not None:
            parts.append(part)

    return parts


def rows_from_batch(parts: List[BatchPart], *, strict: bool = True) -> List[Dict[str, Any]]:
    """Flatten successful OData payloads into rows.

    ``strict`` raises when any part failed. That is the default deliberately: a
    batch where 2 of 5 operations returned 400 must not look like a successful
    batch that happened to return fewer rows.
    """
    failures = [p for p in parts if not p.ok]
    if failures and strict:
        detail = ", ".join(
            f"{p.content_id or '?'}:{p.status} {p.raw_body[:120]}" for p in failures[:5]
        )
        raise RuntimeError(
            f"{len(failures)} of {len(parts)} batch operation(s) failed: {detail}"
        )
    if failures:
        logger.warning(
            "sap_batch_partial_failure",
            failed=len(failures),
            total=len(parts),
            statuses=[p.status for p in failures],
        )

    rows: List[Dict[str, Any]] = []
    for part in parts:
        if not part.ok or part.body is None:
            continue
        payload = part.body
        # OData v2 wraps in {"d": {"results": [...]}}; v4 uses {"value": [...]}.
        if isinstance(payload, dict):
            if isinstance(payload.get("d"), dict) and isinstance(payload["d"].get("results"), list):
                rows.extend(payload["d"]["results"])
                continue
            if isinstance(payload.get("value"), list):
                rows.extend(payload["value"])
                continue
        if isinstance(payload, list):
            rows.extend(payload)
        else:
            rows.append(payload)
    return rows
