"""The receiving half of the edge uplink framing (FS-759).

`edge-agent/opsgrid_agent/compression.py` has existed, correct and tested, since task 22. It
frames a payload as `codec_marker + body` and shrinks a repetitive JSON telemetry batch by
roughly 5-10x, which on a metered or narrowband link is the difference between a backlog that
drains and one that does not.

**Nothing has ever called it.** The agent's orphan register
(`edge-agent/tests/test_no_new_unreachable_modules.py`) is precise about why:

    MISSING: the receiver. It frames output as `codec_marker + body` and nothing in
    backend/app decodes it, so enabling it would make every uplink batch unreadable rather
    than smaller. Needs a backend decision first — this is half a protocol, not unfinished
    wiring.

This file is that decision. It is the half that was missing.

FRAMING IS UNAMBIGUOUS BY CONSTRUCTION, which is what makes this safe to deploy against a
fleet mid-upgrade. A codec marker is `0x00` or `0x01`; a JSON object begins with `{`, which is
`0x7B`. So a message is framed if and only if its first byte is a known marker, and every
agent that has ever run — none of which frame anything — continues to be understood with no
version negotiation on the receiving side at all.

THE OTHER DIRECTION NEEDS NEGOTIATION AND GETS IT. A new agent talking to an OLD backend
would send bytes that backend cannot parse, and every reading would be lost rather than
delayed — the worst possible failure for a store-and-forward system, because the buffer would
mark them sent. So the agent emits `raw` until a heartbeat ack advertises what this backend
can decode. Fail-closed by default: no advertisement means no compression.
"""

from __future__ import annotations

import gzip
from typing import Dict

import structlog

logger = structlog.get_logger()

#: Marker byte -> codec name. THE AUTHORITY for what this backend can decode, and the set
#: `POST /api/v1/edge/heartbeat` advertises to agents.
#:
#: Held against the agent's emittable set by
#: `backend/tests/test_the_agent_emits_no_codec_the_backend_cannot_read.py`. A codec the
#: agent can emit and this cannot decode is not a degraded feature, it is total data loss on
#: the uplink, so the guard is a subset assertion rather than an equality one — this side may
#: run ahead, the agent side may not.
DECODABLE: Dict[int, str] = {
    0x00: "raw",
    0x01: "gzip",
}

#: What the heartbeat advertises. Sorted so the response is deterministic.
ADVERTISED_CODECS = tuple(sorted(DECODABLE.values()))


class UndecodableFrame(ValueError):
    """The first byte looked like a codec marker and named a codec we do not have."""


#: Bytes that can legitimately begin a bare JSON document: the structural openers, the
#: whitespace JSON permits before a value, and the first characters of the scalar forms.
#: Used to tell "an agent that predates the framing" from "a codec this backend does not
#: have" — without it those two are the same byte pattern to us, and the second one gets
#: reported as a JSON parse error about bytes that were never JSON.
_JSON_OPENERS = frozenset(b'{[" \t\r\n-0123456789tfn')


def is_framed(raw: bytes) -> bool:
    """Whether `raw` carries a codec marker rather than being bare JSON.

    A bare JSON object or array starts with `{` (0x7B) or `[` (0x5B), and whitespace-led
    JSON starts with a space, tab, CR or LF — none of which collide with the low marker
    bytes. The disjointness is the reason no version flag is needed on this side, so it is
    asserted by a test rather than left as a comment.
    """
    return bool(raw) and raw[0] in DECODABLE


def decode_frame(raw: bytes) -> bytes:
    """Strip the codec marker and decode the body. Bare JSON passes through untouched."""
    if not raw:
        return raw
    marker = raw[0]
    if marker not in DECODABLE:
        if marker in _JSON_OPENERS:
            # Not framed — an agent predating the framing, which is most of the fleet.
            return raw
        # Neither a codec we know nor the start of a JSON document. Almost always a codec
        # deployed to the fleet ahead of its decoder here, which is a rollout mistake that
        # should appear in the dead-letter topic within seconds and say why. Falling through
        # to `json.loads` instead would report "Expecting value: line 1 column 1", which
        # sends whoever reads it looking at the wrong layer entirely.
        raise UndecodableFrame(
            f"leading byte {marker:#04x} is neither a known codec "
            f"({sorted(DECODABLE)}) nor the start of a JSON document"
        )
    body = raw[1:]
    codec = DECODABLE[marker]
    if codec == "raw":
        return body
    if codec == "gzip":
        try:
            return gzip.decompress(body)
        except (OSError, EOFError) as exc:
            # A corrupt body is a decode failure, not a mystery: name it so the ingestion
            # worker can dead-letter with a reason instead of logging a JSON parse error
            # about bytes that were never JSON.
            raise UndecodableFrame(f"gzip body failed to decompress: {exc}") from exc
    raise UndecodableFrame(f"no decoder for codec {codec!r} (marker {marker:#04x})")
