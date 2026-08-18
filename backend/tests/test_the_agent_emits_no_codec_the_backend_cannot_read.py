"""The agent must never put a codec on the wire this backend cannot decode (FS-759).

`edge-agent/opsgrid_agent/compression.py` frames uplink messages as `codec_marker + body`.
It existed, correct and tested, for a year with **no receiver** — the agent's own orphan
register recorded it as "half a protocol, not unfinished wiring", and turning it on would
have made every uplink batch unreadable rather than smaller.

Both halves now exist, which creates a new way to be wrong: the two sides drifting. A codec
the agent can emit and this backend cannot decode is not a degraded feature. The ingestion
worker cannot parse the message, and the agent's buffer marked the row sent the moment the
broker accepted it — so the reading is gone, not delayed, which is the single outcome
store-and-forward exists to prevent.

**A SUBSET, NOT AN EQUALITY.** This backend may learn a codec before the fleet does; that is
how a rollout works, and an agent that never emits it loses nothing. The reverse cannot be
allowed. Directionality is the whole content of the assertion.

READ BY AST, not imported: the backend test suite does not install the agent package, and the
thing being compared is a dict literal — the source IS the fact. Same arrangement as
`edge-agent/tests/test_priority_tiers_match_the_backend.py`, which holds the priority tiers
across the same boundary for the same reason.
"""

from __future__ import annotations

import ast
import pathlib

from app.services.wire_codec import ADVERTISED_CODECS, DECODABLE, decode_frame, is_framed

AGENT_COMPRESSION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "edge-agent"
    / "opsgrid_agent"
    / "compression.py"
)


def _agent_emittable() -> dict:
    """Extract `EMITTABLE = {name: marker}` from the agent's source."""
    tree = ast.parse(AGENT_COMPRESSION.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "EMITTABLE" not in targets or not isinstance(node.value, ast.Dict):
            continue
        found = {}
        for key, value in zip(node.value.keys, node.value.values):
            if not isinstance(key, ast.Constant):
                continue
            if isinstance(value, ast.Name):
                # `"gzip": _CODEC_GZIP` — resolve the module-level constant.
                found[key.value] = _resolve_constant(tree, value.id)
            elif isinstance(value, ast.Constant):
                # `"brotli": b"\x07"` — an inline literal. HANDLED BECAUSE IT WAS NOT:
                # the first version only accepted `ast.Name`, so an entry written as a
                # literal was silently dropped and the subset assertion below passed over
                # a codec the backend cannot decode. A mutation adding exactly that entry
                # survived, which is how this was found.
                found[key.value] = value.value
        return found
    return {}


def _resolve_constant(tree: ast.Module, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(node.value, ast.Constant):
                        return node.value.value
    return None


class TestTheSweepCanSeeItsSubject:
    def test_the_agent_source_is_where_this_thinks_it_is(self):
        assert AGENT_COMPRESSION.exists(), f"agent compression moved: {AGENT_COMPRESSION}"

    def test_the_emittable_table_was_actually_parsed(self):
        """Vacuity. An AST walk that matches nothing returns {}, and every subset assertion
        below passes trivially over an empty set — including after somebody renames
        `EMITTABLE` or converts it to a computed value."""
        emittable = _agent_emittable()
        assert len(emittable) >= 2, (
            f"parsed only {emittable} from the agent; the extractor has stopped matching "
            "and this whole file is measuring nothing"
        )
        assert all(isinstance(marker, bytes) for marker in emittable.values()), emittable


class TestEveryEmittableCodecIsDecodable:
    def test_the_backend_can_decode_everything_the_agent_can_emit(self):
        emittable = set(_agent_emittable())
        decodable = set(DECODABLE.values())
        orphaned = sorted(emittable - decodable)
        assert not orphaned, (
            f"the agent can emit {orphaned} and this backend cannot decode it. That is not "
            "a degraded feature: ingestion cannot parse the message, and the agent's buffer "
            "already marked the row sent when the broker accepted it. Those readings are "
            "gone. Add the decoder here BEFORE the agent gains the codec."
        )

    def test_the_markers_agree_and_not_only_the_names(self):
        """A name in both tables mapped to different bytes decodes as the wrong codec, or
        as nothing — which the name comparison above would not notice."""
        emittable = _agent_emittable()
        by_marker = {marker: name for marker, name in DECODABLE.items()}
        for name, marker in emittable.items():
            if name not in set(DECODABLE.values()):
                continue
            assert len(marker) == 1, f"{name} marker is {marker!r}, expected one byte"
            assert by_marker.get(marker[0]) == name, (
                f"the agent frames {name!r} as {marker!r} ({marker[0]:#04x}) and this "
                f"backend reads {marker[0]:#04x} as {by_marker.get(marker[0])!r}"
            )

    def test_the_advertised_set_is_what_can_actually_be_decoded(self):
        """The heartbeat tells agents what to emit. Advertising a codec with no decoder
        instructs the fleet to send unreadable bytes."""
        assert set(ADVERTISED_CODECS) == set(DECODABLE.values()), (
            f"advertised {sorted(ADVERTISED_CODECS)} but can decode "
            f"{sorted(set(DECODABLE.values()))}"
        )


class TestTheAdvertisementReachesTheAgent:
    """Computing the set is not advertising it.

    A mutation emptying `HeartbeatAck.wire_codecs` survived every other assertion here: the
    codecs were still correct, still consistent, still decodable — and no agent would ever
    be told, so the whole fleet would stay on raw forever and the feature would be a
    negotiation that always says no. Silent, and indistinguishable from working.
    """

    def test_the_heartbeat_ack_carries_the_codecs_by_default(self):
        from app.api.edge_fleet import HeartbeatAck

        ack = HeartbeatAck(ok=True, server_time="2026-08-18T10:00:00+00:00")
        assert ack.wire_codecs, (
            "the heartbeat ack advertises nothing, so every agent stays on `raw` forever "
            "and the negotiation can only ever refuse"
        )
        assert set(ack.wire_codecs) == set(ADVERTISED_CODECS)

    def test_the_field_survives_serialisation(self):
        """FastAPI builds the response from the model. A field the model computes and the
        schema drops is exactly how `dropped` went missing from the fleet view (FS-591)."""
        from app.api.edge_fleet import HeartbeatAck

        dumped = HeartbeatAck(ok=True, server_time="2026-08-18T10:00:00+00:00").model_dump()
        assert "wire_codecs" in dumped, dumped
        assert set(dumped["wire_codecs"]) == set(ADVERTISED_CODECS)


class TestFramedAndBareAreDistinguishable:
    """No version flag is needed on the receiving side, and that rests on one fact."""

    def test_no_marker_collides_with_the_start_of_json(self):
        json_openers = {ord(c) for c in '{[" \t\r\n-0123456789tfn'}
        collisions = sorted(set(DECODABLE) & json_openers)
        assert not collisions, (
            f"codec markers {collisions} can also begin a JSON document, so a bare payload "
            "from an older agent would be mistaken for a frame and silently mangled"
        )

    def test_bare_json_from_an_older_agent_passes_through_untouched(self):
        payload = b'{"asset_id": "press-01", "payload": {"vibration": 1.0}}'
        assert not is_framed(payload)
        assert decode_frame(payload) == payload

    def test_a_framed_message_is_recognised_as_framed(self):
        """The positive half. `assert not is_framed(...)` alone passes against an
        `is_framed` that always returns False, which a mutation demonstrated."""
        assert is_framed(b"\x00" + b'{"a": 1}')
        assert is_framed(b"\x01" + b"compressed-bytes")
        assert not is_framed(b"")

    def test_a_raw_frame_and_a_gzip_frame_both_decode(self):
        import gzip

        payload = b'{"asset_id": "press-01"}'
        assert decode_frame(b"\x00" + payload) == payload
        assert decode_frame(b"\x01" + gzip.compress(payload)) == payload

    def test_a_corrupt_gzip_body_is_named_rather_than_mystifying(self):
        from app.services.wire_codec import UndecodableFrame
        import pytest

        with pytest.raises(UndecodableFrame, match="gzip"):
            decode_frame(b"\x01not actually gzip")
