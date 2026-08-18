"""S7 — compression on the uplink, negotiated (FS-759).

`compression.py` shrinks a repetitive JSON telemetry batch by 5-10x, which on a metered or
narrowband link is the difference between a backlog that drains and one that does not. It has
been correct and tested since task 22, and **nothing ever called it**, because the receiving
half did not exist. The agent's own orphan register was precise about that:

    MISSING: the receiver. ... Needs a backend decision first — this is half a protocol,
    not unfinished wiring.

Both halves now exist, and the interesting part is not the compression. It is the direction
of the compatibility risk.

  * A NEW BACKEND reading an OLD AGENT needs nothing: bare JSON begins with `{` and a codec
    marker is `0x00`/`0x01`, so the two are disjoint and the receiver simply tells them
    apart.
  * A NEW AGENT talking to an OLD BACKEND is the dangerous direction. Those bytes are
    unparseable there — and the store-and-forward buffer marks a row sent the moment the
    broker accepts it, so the readings are **gone rather than delayed**. That is the one
    outcome the entire buffer exists to prevent, produced by an optimisation.

So the agent emits `raw` until a heartbeat ack tells it what the backend can decode. These
scenarios are about that gate, because a mutation pass found the backend half well covered
and the agent's negotiate-and-emit path covered by nothing at all.
"""

from __future__ import annotations

import gzip
import json

import pytest

from opsgrid_agent.compression import EMITTABLE, compress, decompress
from opsgrid_agent.heartbeat import HeartbeatReporter
from opsgrid_agent.main import EdgeAgent

pytestmark = pytest.mark.ddil


def _batch(rows: int = 500) -> dict:
    return {
        "asset_id": "press-01",
        "backfilled": True,
        "readings": [{"vibration": 1.25, "temp_bearing": 71.0, "seq": i}
                     for i in range(rows)],
    }


class _Agent:
    """Just enough of EdgeAgent for the serialiser, which is the whole point."""

    def __init__(self, reporter=None):
        self.heartbeat_reporter = reporter
        self._serialize_uplink = EdgeAgent._serialize_uplink.__get__(self)
        self._negotiated_codecs = EdgeAgent._negotiated_codecs.__get__(self)


def _reporter(ack: dict) -> HeartbeatReporter:
    reporter = HeartbeatReporter(
        "http://cloud", "1.0", lambda: {}, lambda url, body, headers: (200, ack)
    )
    reporter.send_once()
    return reporter


class TestTheGate:
    def test_an_agent_that_has_never_heard_from_the_backend_does_not_compress(self):
        """The state every agent boots into, and the one an agent stays in when the cloud
        URL is unset or the link has been down since start."""
        framed = _Agent()._serialize_uplink(_batch())
        assert framed[:1] == b"\x00", (
            "the agent compressed before any backend told it that it could. Against a "
            "deployment that cannot decompress, every one of those readings is lost — the "
            "buffer marked them sent when the broker accepted them."
        )
        assert json.loads(decompress(framed)) == _batch()

    def test_an_older_backend_that_advertises_nothing_leaves_it_raw(self):
        agent = _Agent(_reporter({"ok": True, "server_time": "2026-08-18T10:00:00+00:00"}))
        assert agent._negotiated_codecs() == ("raw",)
        assert agent._serialize_uplink(_batch())[:1] == b"\x00"

    def test_a_backend_that_advertises_gzip_unlocks_it(self):
        agent = _Agent(_reporter({"ok": True, "wire_codecs": ["raw", "gzip"]}))
        assert agent._negotiated_codecs() == ("gzip", "raw")

        framed = agent._serialize_uplink(_batch())
        assert framed[:1] == b"\x01", "the advertisement was accepted and then ignored"
        assert json.loads(decompress(framed)) == _batch()

    def test_the_shrink_is_worth_the_byte_it_costs(self):
        """Measured, not assumed. If a realistic batch does not shrink meaningfully, the
        framing is pure overhead and the negotiation is complexity for nothing."""
        agent = _Agent(_reporter({"ok": True, "wire_codecs": ["raw", "gzip"]}))
        plain = json.dumps(_batch()).encode()
        framed = agent._serialize_uplink(_batch())
        ratio = len(plain) / len(framed)
        assert ratio > 5, f"only {ratio:.1f}x smaller on a realistic telemetry batch"

    def test_a_small_message_stays_raw_even_when_gzip_is_allowed(self):
        """The control case. gzip on a 40-byte heartbeat-sized payload costs CPU and makes
        it bigger, and a serialiser that compressed everything would pass the tests above."""
        agent = _Agent(_reporter({"ok": True, "wire_codecs": ["raw", "gzip"]}))
        framed = agent._serialize_uplink({"asset_id": "a", "payload": {"v": 1}})
        assert framed[:1] == b"\x00"


class TestTheNegotiationItself:
    def test_a_missing_field_is_not_an_advertisement(self):
        assert _reporter({"ok": True}).wire_codecs == ("raw",)

    def test_a_malformed_advertisement_is_ignored_rather_than_parsed_loosely(self):
        for junk in ("gzip", {"gzip": True}, None, 42):
            assert _reporter({"ok": True, "wire_codecs": junk}).wire_codecs == ("raw",)

    def test_an_advertisement_without_raw_is_refused(self):
        """A backend that cannot decode `raw` cannot decode anything this agent frames, so
        the claim is incoherent. Accepting it would enable gzip on the word of a response
        that has already contradicted itself."""
        assert _reporter({"ok": True, "wire_codecs": ["gzip"]}).wire_codecs == ("raw",)

    def test_unknown_codec_names_do_not_widen_what_is_emitted(self):
        reporter = _reporter({"ok": True, "wire_codecs": ["raw", "brotli"]})
        agent = _Agent(reporter)
        framed = agent._serialize_uplink(_batch())
        assert framed[:1] == b"\x00", (
            "the agent framed with something it was told about but cannot emit; the "
            "negotiated set is an intersection, not a substitution"
        )

    def test_a_non_200_ack_still_calibrates_the_codecs(self):
        """Same reasoning the clock sampling already uses: a 401 carrying a body is still
        the backend talking, and its stated capabilities are still true."""
        reporter = HeartbeatReporter(
            "http://cloud", "1.0", lambda: {},
            lambda url, body, headers: (401, {"wire_codecs": ["raw", "gzip"]}),
        )
        reporter.send_once()
        assert reporter.wire_codecs == ("gzip", "raw")

    def test_a_failed_heartbeat_does_not_narrow_an_established_set(self):
        """One missed heartbeat is not evidence the backend was downgraded, and flipping
        the wire format on a flaky link is its own defect."""
        acks = iter([
            (200, {"ok": True, "wire_codecs": ["raw", "gzip"]}),
            (503, {}),
            (503, {}),
        ])
        reporter = HeartbeatReporter(
            "http://cloud", "1.0", lambda: {}, lambda url, body, headers: next(acks)
        )
        reporter.send_once()
        assert reporter.wire_codecs == ("gzip", "raw")
        reporter.send_once()
        reporter.send_once()
        assert reporter.wire_codecs == ("gzip", "raw")


class TestTheFramingRoundTrips:
    @pytest.mark.parametrize("codec", sorted(EMITTABLE))
    def test_every_codec_this_agent_can_emit_decodes_back_to_the_original(self, codec):
        payload = json.dumps(_batch()).encode()
        framed, _ = compress(payload, allowed=[codec, "raw"])
        assert decompress(framed) == payload

    def test_the_gzip_frame_is_ordinary_gzip_a_backend_can_read(self):
        """Not a private format. The receiving half calls `gzip.decompress` on the body,
        so what this produces has to be exactly that and nothing cleverer."""
        payload = json.dumps(_batch()).encode()
        framed, compressed = compress(payload, allowed=["raw", "gzip"])
        assert compressed is True
        assert gzip.decompress(framed[1:]) == payload
