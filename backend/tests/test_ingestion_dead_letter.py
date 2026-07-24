"""IngestionWorker dead-letter path.

A message the worker can't process used to be logged and then silently lost as
auto-commit advanced the offset past it. It now goes to a DLQ topic with enough
provenance to replay. This tests the envelope and that a DLQ failure never
crashes the worker.
"""

import asyncio
import json
from types import SimpleNamespace

from app.core.config import settings
from app.workers.ingestion import IngestionWorker


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _FakeProducer:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    async def send_and_wait(self, topic, value, key=None):
        if self.fail:
            raise ConnectionError("broker down")
        self.sent.append((topic, value, key))


def _msg(**over):
    base = dict(topic="telemetry.org1", partition=2, offset=99,
                key=b"asset-1", value={"asset_id": "a1", "bad": True})
    base.update(over)
    return SimpleNamespace(**base)


def test_dead_letters_poison_message_with_provenance():
    async def scenario():
        w = IngestionWorker()
        w._producer = _FakeProducer()
        await w._dead_letter(_msg(), ValueError("boom"))
        return w._producer.sent

    sent = run(scenario())
    assert len(sent) == 1
    topic, env, key = sent[0]
    assert topic == settings.REDPANDA_INGESTION_DLQ_TOPIC
    assert env["message_type"] == "dead_letter"
    assert env["reason"] == "boom" and env["error_type"] == "ValueError"
    assert env["source_topic"] == "telemetry.org1"
    assert env["source_partition"] == 2 and env["source_offset"] == 99
    assert env["payload"] == {"asset_id": "a1", "bad": True}
    assert key == b"asset-1"
    # envelope must be JSON-serializable (the real producer serializes it)
    json.dumps(env)


def test_dlq_failure_does_not_raise():
    async def scenario():
        w = IngestionWorker()
        w._producer = _FakeProducer(fail=True)
        # Must not raise even though the DLQ publish fails.
        await w._dead_letter(_msg(), RuntimeError("x"))

    run(scenario())  # no exception = pass


def test_no_producer_is_a_noop():
    async def scenario():
        w = IngestionWorker()
        w._producer = None
        await w._dead_letter(_msg(), RuntimeError("x"))

    run(scenario())
