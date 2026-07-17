"""Uplink compression (task 22).

Telemetry batches are JSON and highly repetitive (repeated keys, similar
values), so gzip typically shrinks them 5-10x — a big win on metered or
low-bandwidth edge links. Compression is applied only above a size threshold
(tiny payloads gain nothing and waste CPU) and is self-describing via a
one-byte codec marker, so the receiver can decode without out-of-band state.
"""

import gzip
from typing import Tuple

# One-byte prefix marks how the body is encoded, so decode needs no side channel.
_CODEC_RAW = b"\x00"
_CODEC_GZIP = b"\x01"

DEFAULT_MIN_SIZE = 512  # bytes below which gzip is not worth it


def compress(data: bytes, min_size: int = DEFAULT_MIN_SIZE) -> Tuple[bytes, bool]:
    """Return (framed_bytes, was_compressed).

    Frames as ``codec_marker + body``. Falls back to raw when the payload is
    small or when gzip fails to shrink it (already-compressed content).
    """
    if len(data) < min_size:
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
