"""Backpressure reaches the producer, and fails toward sending (FS-865/866).

THE LOSS THIS PREVENTS. The agent drains its store-and-forward buffer into Redpanda as
fast as the link allows. Kafka gives a producer no view of consumer lag, so when the
ingestion worker falls behind, nothing tells the agent — the queue grows until the worker
starts SHEDDING, and readings are destroyed that were, moments earlier, sitting in an
encrypted durable buffer on the device with days of capacity.

The edge holds data well. The cloud, under pressure, holds it by dropping it. So the
correct response to a full pipeline is to slow the producer and leave the data where it is
safe — not to accept it and destroy it.

WHY NOT ADMISSION CONTROL AT THE INGEST ENDPOINT, which is what FS-865 asked for: that
endpoint exists and nothing calls it (`api/edge_ingest.py` says so in its own header). The
agent publishes straight to the broker, so the door to guard is the drain rate, not an
HTTP handler.

EVERY FAILURE DIRECTION HERE IS "KEEP SENDING". A backpressure mechanism that fails toward
throttling can silence a fleet on a Redis outage, a typo, or a dead worker's stale key —
and a silenced fleet loses data the same way a shedding one does, only quieter.
"""
from __future__ import annotations

import pytest

from app.services import ingest_pressure


class TestTheLevelMeansSomething:
    def test_a_quiet_pipeline_is_normal(self):
        assert ingest_pressure.level_for(shed_rate_per_sec=0, lag_messages=0) == "normal"

    def test_any_shedding_is_at_least_elevated(self):
        """Shedding IS data loss, so by the time it starts, asking agents to slow down is
        overdue rather than premature."""
        assert ingest_pressure.level_for(0.1, 0) == "elevated"

    def test_lag_alone_is_elevated_not_critical(self):
        """A backlog that is draining is a queue doing its job. Only lag WITH shedding
        says the pipeline cannot catch up."""
        assert ingest_pressure.level_for(0, 50_000) == "elevated"

    def test_shedding_while_behind_is_critical(self):
        assert ingest_pressure.level_for(2.0, 50_000) == "critical"


class TestItFailsTowardSending:
    @pytest.mark.asyncio
    async def test_an_unreachable_redis_reads_normal(self, monkeypatch):
        """A Redis outage must restore today's behaviour, not throttle a fleet on a guess.
        This is the difference between a mechanism that degrades and one that becomes the
        incident."""
        async def _boom():
            raise ConnectionError("redis is gone")

        monkeypatch.setattr(
            ingest_pressure.redis_client.breaker, "call", lambda fn: _boom()
        )
        assert await ingest_pressure.current() == "normal"

    @pytest.mark.asyncio
    async def test_an_unrecognised_value_reads_normal(self, monkeypatch):
        """A typo upstream must not be able to silence the fleet."""
        async def _weird():
            return "SLOW_DOWN_A_LOT"

        monkeypatch.setattr(
            ingest_pressure.redis_client.breaker, "call", lambda fn: _weird()
        )
        assert await ingest_pressure.current() == "normal"

    @pytest.mark.asyncio
    async def test_publishing_never_raises(self, monkeypatch):
        """The worker publishing its own pressure must never be the reason the worker
        under pressure stops working."""
        async def _boom():
            raise ConnectionError("redis is gone")

        monkeypatch.setattr(
            ingest_pressure.redis_client.breaker, "call", lambda fn: _boom()
        )
        await ingest_pressure.publish("critical")  # must not raise

    def test_the_key_expires(self):
        """THE SAFETY PROPERTY. A backpressure signal with no TTL is a fleet-wide outage
        waiting for the process that wrote it to die: a worker that crashes while
        'critical' would throttle every agent forever."""
        assert 0 < ingest_pressure.TTL_SECONDS <= 300


class TestTheHeartbeatCarriesIt:
    def test_the_ack_defaults_to_normal(self):
        """An old backend omits the field and a new one may too; either way the agent must
        behave as it does today."""
        from app.api.edge_fleet import HeartbeatAck

        assert HeartbeatAck(ok=True, server_time="t").ingest_pressure == "normal"

    def test_the_endpoint_reads_the_current_level(self):
        """Asserted structurally: the ack is only a channel if something fills it."""
        import ast
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1] / "app/api/edge_fleet.py"
        ).read_text()
        tree = ast.parse(source)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "heartbeat"
        )
        called = {
            node.func.attr
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "current" in called, (
            "the heartbeat no longer reads the ingest pressure, so the ack always says "
            "normal and no agent can ever be asked to slow down"
        )


class TestTheWorkerIsTheOnlyThingThatKnows:
    def test_it_publishes_from_the_consume_loop(self):
        """Consumer lag is invisible to a producer and to the API. The component doing the
        shedding is the only one that can say so; the heartbeat merely relays it."""
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1] / "app/workers/ingestion.py"
        ).read_text()
        assert "_publish_ingest_pressure" in source
        assert "ingest_pressure.publish" in source

    def test_unknown_lag_does_not_throttle(self):
        """`_consumer_lag` returns 0 when it cannot tell. An unknown lag is not evidence of
        pressure, and guessing high would slow a fleet on no information."""
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1] / "app/workers/ingestion.py"
        ).read_text()
        body = source[source.index("def _consumer_lag"):]
        assert "return 0" in body[: body.index("\n    async def", 1) if "\n    async def" in body else len(body)]
