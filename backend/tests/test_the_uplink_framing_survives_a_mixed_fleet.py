"""A fleet is never upgraded all at once, and ingestion has to read both (FS-759).

The uplink gained a framing — `codec_marker + body` — so a narrowband edge link can send a
compressed telemetry batch instead of raw JSON. The moment that ships, the broker carries two
wire formats at the same time: every agent already in the field sends bare JSON, and only
agents on the new build frame anything. There is no flag day; a gateway on a boat may be
months behind.

`_deserialize_uplink` is the one function that has to be right about that. It runs on every
message, it has no context, and if it is wrong in either direction the failure is total
rather than partial — an unparseable message is dropped or dead-lettered, and the agent's
buffer already marked the row sent when the broker accepted it.

These are the cases it must get right, asserted against the real deserialiser rather than
against a description of it.
"""

from __future__ import annotations

import gzip
import json

import pytest

from app.services.wire_codec import UndecodableFrame
from app.workers.ingestion import _deserialize_uplink

READING = {
    "timestamp_edge": "2026-08-18T10:00:00+00:00",
    "asset_id": "press-01",
    "payload": {"vibration": 1.25, "temp_bearing": 71.0},
    "sequence_num": 41,
    "backfilled": True,
}


def _json_bytes(value=READING) -> bytes:
    return json.dumps(value).encode("utf-8")


class TestTheOldFleet:
    def test_bare_json_from_an_unupgraded_agent_still_parses(self):
        assert _deserialize_uplink(_json_bytes()) == READING

    def test_a_bare_payload_starting_with_whitespace_still_parses(self):
        """`json.dumps` never leads with whitespace, but a hand-rolled producer or a proxy
        that pretty-prints might. A leading space must not be mistaken for a codec."""
        assert _deserialize_uplink(b"  " + _json_bytes()) == READING

    def test_a_bare_json_array_still_parses(self):
        batch = [READING, READING]
        assert _deserialize_uplink(json.dumps(batch).encode()) == batch


class TestTheNewFleet:
    def test_a_raw_framed_message_parses(self):
        assert _deserialize_uplink(b"\x00" + _json_bytes()) == READING

    def test_a_gzip_framed_message_parses(self):
        assert _deserialize_uplink(b"\x01" + gzip.compress(_json_bytes())) == READING

    def test_a_realistic_batch_actually_shrinks(self):
        """The point of the exercise. A telemetry batch is highly repetitive, and on a
        metered link the ratio is the difference between a backlog that drains and one that
        does not — so it is measured here rather than asserted in a comment."""
        batch = [dict(READING, sequence_num=i) for i in range(500)]
        plain = json.dumps(batch).encode()
        framed = b"\x01" + gzip.compress(plain)

        assert _deserialize_uplink(framed) == batch
        ratio = len(plain) / len(framed)
        assert ratio > 5, f"only {ratio:.1f}x smaller; the framing is not earning its byte"


class TestBothAtOnce:
    def test_the_two_formats_interleave_without_state(self):
        """The deserialiser sees one message at a time from a shared topic, in whatever
        order the partitions deliver. It must carry no state between them."""
        messages = [
            _json_bytes(),                                    # old agent
            b"\x01" + gzip.compress(_json_bytes()),           # new agent, compressed
            _json_bytes(),                                    # old agent again
            b"\x00" + _json_bytes(),                          # new agent, below threshold
        ]
        assert [_deserialize_uplink(m) for m in messages] == [READING] * 4


class TestWhatMustFailLoudly:
    def test_a_frame_naming_an_unknown_codec_raises(self):
        """Not silently returned as bytes. The caller dead-letters on the exception, and a
        message this backend genuinely cannot read must reach that path — a fleet emitting
        a codec deployed ahead of its decoder is a rollout mistake that should be visible
        in the dead-letter topic within seconds."""
        with pytest.raises(UndecodableFrame):
            _deserialize_uplink(b"\x02" + _json_bytes())

    def test_a_corrupt_compressed_body_raises_about_compression(self):
        with pytest.raises(UndecodableFrame, match="gzip"):
            _deserialize_uplink(b"\x01truncated-not-gzip")

    def test_a_frame_wrapping_something_that_is_not_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _deserialize_uplink(b"\x01" + gzip.compress(b"not json at all"))
