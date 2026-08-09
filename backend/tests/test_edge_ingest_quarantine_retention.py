"""A quarantined reading must still exist afterwards.

THE DEFECT. `EdgeIngestGateway.ingest` validated each reading and, on failure, called
`self._quarantine_sink(agent_id, reading, err)` and incremented an integer. The API
constructs the gateway with no sink (`api/edge_ingest.py`), so the default ran:

    def _default_quarantine(self, agent_id, reading, reason):
        logger.warning("edge_ingest_quarantined", agent_id=agent_id, reason=reason)

`reading` is accepted and never used. The payload was discarded — not written to a
table, not published to a topic, not even in the log line — and then
`POST /api/v1/edge/ingest` answered `quarantined: 47`.

The count was true and the word was not. "Quarantined" means set aside for inspection;
the module docstring said these were "diverted to a dead-letter sink." An operator
reading that number had no way to learn it described 47 readings that no longer existed
anywhere, and no way to find out what was wrong with the agent producing them —
precisely the moment you need the data most.

THE FIX has two halves, and both are tested here because either alone leaves a hole:
retention in `IngestResult.quarantined`, so every caller gets the readings whether or
not it injects a sink; and a real dead-letter topic hop in the endpoint, so they
outlive the request.

`summary["quarantined"]` is still the count, so the API response shape is untouched.
"""

from __future__ import annotations

from datetime import datetime

from app.services.edge_ingest import EdgeIngestGateway, RedpandaForwarder

GOOD = {"asset_id": "a", "timestamp_edge": "2026-07-27T00:00:00Z",
        "payload": {"temp": 1.0}, "sequence_num": 1}
MALFORMED = {"asset_id": "m", "payload": {}}  # no timestamp_edge


def _gateway(**kw) -> EdgeIngestGateway:
    return EdgeIngestGateway(**kw)


class TestTheReadingSurvives:
    def test_the_payload_is_retained_not_just_counted(self):
        """THE ASSERTION THIS FILE EXISTS FOR. Before the fix this reading existed
        nowhere after ingest returned."""
        result = _gateway().ingest("agent-1", [GOOD, MALFORMED])

        assert len(result.quarantined) == 1
        retained = result.quarantined[0]["reading"]
        assert retained == MALFORMED, (
            "the quarantined reading itself is gone; only a count survived"
        )

    def test_the_record_says_who_sent_it_and_why_it_failed(self):
        """A retained payload with no reason is barely better than a count — the
        investigation starts from 'which agent, and what was wrong with it'."""
        record = _gateway().ingest("agent-7", [MALFORMED]).quarantined[0]
        assert record["agent_id"] == "agent-7"
        assert record["reason"], "no rejection reason retained"
        assert isinstance(record["reason"], str)
        datetime.fromisoformat(record["quarantined_at"].replace("Z", "+00:00"))

    def test_a_reading_that_is_not_even_a_dict_is_still_kept(self):
        """The old code passed `{}` to the sink for a non-dict reading, so the one
        detail that mattered — that the agent sent something that was not a reading at
        all — was the detail it threw away."""
        result = _gateway().ingest("agent-1", ["not-a-dict", 42])
        assert len(result.quarantined) == 2
        raws = [r["reading"].get("_raw") for r in result.quarantined]
        assert "'not-a-dict'" in raws and "42" in raws, f"got {raws}"

    def test_retention_happens_with_no_sink_injected(self):
        """The API injects none, which is exactly the configuration that lost data."""
        assert _gateway().ingest("agent-1", [MALFORMED]).quarantined

    def test_an_injected_sink_still_receives_the_reading(self):
        """Retention must not have replaced the extension point — a deployment with a
        durable sink keeps working."""
        seen = []
        gw = _gateway(quarantine_sink=lambda aid, r, reason: seen.append((aid, r, reason)))
        gw.ingest("agent-1", [MALFORMED])
        assert len(seen) == 1
        assert seen[0][0] == "agent-1"
        assert seen[0][1] == MALFORMED


class TestTheApiContractIsUnchanged:
    def test_summary_still_reports_an_integer_count(self):
        """`IngestSummary.quarantined` is typed `int`. Changing the field to a list
        must not change what the endpoint returns."""
        summary = _gateway().ingest("agent-1", [GOOD, MALFORMED, MALFORMED]).summary
        assert summary["quarantined"] == 2
        assert isinstance(summary["quarantined"], int)

    def test_valid_readings_are_unaffected(self):
        result = _gateway().ingest("agent-1", [GOOD])
        assert len(result.accepted) == 1
        assert result.quarantined == []


class _Producer:
    """Records what was published instead of talking to a broker."""

    def __init__(self, fail: bool = False):
        self.sent = []
        self._fail = fail

    async def send_and_wait(self, topic, value):
        if self._fail:
            raise RuntimeError("broker down")
        self.sent.append((topic, value))

    async def start(self):
        return None


class TestTheDeadLetterHop:
    async def test_records_reach_a_dead_letter_topic(self):
        producer = _Producer()
        forwarder = RedpandaForwarder(producer_factory=lambda: producer)
        records = _gateway().ingest("agent-9", [MALFORMED]).quarantined

        sent = await forwarder.forward_quarantined("agent-9", records)

        assert sent == 1
        topic, value = producer.sent[0]
        assert topic == "telemetry.dlq.agent-9"
        assert value["reading"] == MALFORMED, "the payload did not survive the hop"

    async def test_the_topic_keys_on_the_agent_not_the_reading(self):
        """A reading that failed validation cannot be trusted for routing — the
        malformed field may BE `asset_id`. Keying on it would scatter dead letters
        under attacker- or bug-controlled topic names, and lose the one identity that
        was actually verified (the client certificate)."""
        producer = _Producer()
        forwarder = RedpandaForwarder(producer_factory=lambda: producer)
        hostile = {"asset_id": "../../evil", "payload": {}}  # no timestamp_edge
        records = _gateway().ingest("agent-9", [hostile]).quarantined

        await forwarder.forward_quarantined("agent-9", records)

        assert producer.sent[0][0] == "telemetry.dlq.agent-9"
        assert "evil" not in producer.sent[0][0]

    async def test_a_broker_outage_is_counted_rather_than_raised(self):
        """The endpoint fires this as a background task; an exception escaping here
        would be swallowed by the event loop and the drop would be invisible."""
        forwarder = RedpandaForwarder(producer_factory=lambda: _Producer(fail=True))
        records = _gateway().ingest("agent-9", [MALFORMED]).quarantined

        assert await forwarder.forward_quarantined("agent-9", records) == 0
        assert forwarder.dropped == 1

    async def test_no_broker_drops_are_counted_not_silent(self):
        forwarder = RedpandaForwarder(producer_factory=lambda: None)
        records = _gateway().ingest("agent-9", [MALFORMED, MALFORMED]).quarantined

        assert await forwarder.forward_quarantined("agent-9", records) == 0
        assert forwarder.dropped == 2


class TestTheDefaultSinkNoLongerCarriesRetention:
    def test_the_default_sink_is_log_only_and_that_is_now_fine(self):
        """Pins the division of responsibility. If retention ever moves back into the
        sink, a deployment that injects its own would silently stop retaining — the
        original bug, one level up."""
        gw = _gateway()
        result = gw.ingest("agent-1", [MALFORMED])
        assert result.quarantined, "retention is not in ingest()"

        # Calling the default sink directly must not itself accumulate state.
        gw._default_quarantine("agent-1", MALFORMED, "reason")
        assert len(result.quarantined) == 1


class TestAcceptedIsNotForwarded:
    """`accepted` and `forwarded` are different facts, and used to be reported as one.

    A reading is ACCEPTED when it passes validation, dedup and sequencing. It is
    FORWARDED only if its organisation can be resolved, because the topic name embeds
    the org. That lookup reads `assets` — FORCE ROW LEVEL SECURITY — through a session
    with no tenant GUC, so it returns None for every asset and nothing is published.

    Verified against a real database: `_resolve_org` returns None for an asset that
    demonstrably exists. The response nonetheless reported `accepted: N`, from which a
    caller could only infer delivery.

    Nothing calls this endpoint today — the edge agent publishes straight to the broker —
    which is exactly why a total forwarding failure went unnoticed. The counts are now
    separate so that if anyone does wire it up, the gap is visible in the response rather
    than inferred from a silent topic.
    """

    def test_the_summary_reports_forwarded_separately(self):
        from app.api.edge_ingest import IngestSummary

        fields = set(IngestSummary.model_fields)
        assert "forwarded" in fields, (
            "the ingest summary no longer distinguishes forwarded from accepted, so a "
            "caller cannot tell delivery from validation"
        )
        assert "accepted" in fields

    def test_forwarded_defaults_to_zero_not_to_accepted(self):
        """The default must not flatter the result. If `forwarded` ever defaults to the
        accepted count, the distinction is decorative."""
        from app.api.edge_ingest import IngestSummary

        summary = IngestSummary(accepted=5, deduped=0, quarantined=0, out_of_order=0, gaps=0)
        assert summary.forwarded == 0
