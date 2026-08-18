"""Uplink compression (task 22).

Telemetry batches are JSON and highly repetitive (repeated keys, similar
values), so gzip typically shrinks them 5-10x — a big win on metered or
low-bandwidth edge links. Compression is applied only above a size threshold
(tiny payloads gain nothing and waste CPU) and is self-describing via a
one-byte codec marker, so the receiver can decode without out-of-band state.
"""

import gzip
from typing import Iterable, Optional, Tuple

# One-byte prefix marks how the body is encoded, so decode needs no side channel.
_CODEC_RAW = b"\x00"
_CODEC_GZIP = b"\x01"

#: Codec name -> marker. THE AUTHORITY for what this agent can put on the wire (FS-759).
#:
#: Held against `backend/app/services/wire_codec.py:DECODABLE` by
#: `backend/tests/test_the_agent_emits_no_codec_the_backend_cannot_read.py`. The assertion is
#: a SUBSET, not an equality: the backend may learn a codec before the fleet does, but an
#: agent that emits something the backend cannot read does not degrade — every reading is
#: lost, because the buffer marks it sent.
EMITTABLE = {
    "raw": _CODEC_RAW,
    "gzip": _CODEC_GZIP,
}

DEFAULT_MIN_SIZE = 512  # bytes below which gzip is not worth it


def compress(
    data: bytes,
    min_size: int = DEFAULT_MIN_SIZE,
    allowed: Optional[Iterable[str]] = None,
) -> Tuple[bytes, bool]:
    """Return (framed_bytes, was_compressed).

    Frames as ``codec_marker + body``. Falls back to raw when the payload is
    small or when gzip fails to shrink it (already-compressed content).

    `allowed` is what the BACKEND said it can decode, from the heartbeat ack (FS-759).
    Omitting it means raw only — fail closed, deliberately. A new agent pointed at an older
    backend that never advertised anything must not compress: those bytes would be
    unparseable there, and the buffer marks a message sent once the broker accepts it, so
    the failure is silent permanent loss rather than a retry. `raw` framing is still applied
    because a leading `0x00` is unambiguous against JSON's `{` and costs one byte.
    """
    permitted = set(allowed) if allowed is not None else {"raw"}
    if len(data) < min_size or "gzip" not in permitted:
        return _CODEC_RAW + data, False
    packed = gzip.compress(data, compresslevel=6)
    if len(packed) >= len(data):
        return _CODEC_RAW + data, False
    return _CODEC_GZIP + packed, True


def decompress(framed: bytes) -> bytes:
    """Invert :func:`compress`, dispatching on the codec marker."""
    if not framed:
        return b""
    marker, body = framed[:1], framed[1:]
    if marker == _CODEC_GZIP:
        return gzip.decompress(body)
    if marker == _CODEC_RAW:
        return body
    raise ValueError(f"unknown compression codec marker: {marker!r}")
