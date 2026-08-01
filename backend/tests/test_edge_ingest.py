"""Tests for the cloud ingest-gateway guards (tasks 11-15)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.edge_ingest import (
    DedupCache,
    EdgeIngestGateway,
    RateLimited,
    SequenceTracker,
    TokenBucket,
    idempotency_key,
    validate_reading,
)

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def reading(asset="a1", seq=1, ts=None, payload=None):
    return {
        "asset_id": asset,
        "timestamp_edge": (ts or NOW).isoformat(),
        "topic": "telemetry",
        "payload": payload if payload is not None else {"v": 1},
        "sequence_num": seq,
    }


# --- task 11: validation ------------------------------------------------------

def test_validation_accepts_good_reading():
    assert validate_reading(reading()) is None


@pytest.mark.parametrize("bad", [
    {"timestamp_edge": NOW.isoformat(), "payload": {}},          # no asset
    {"asset_id": "a", "payload": {}},                            # no ts
    {"asset_id": "a", "timestamp_edge": "nope", "payload": {}},  # bad ts
    {"asset_id": "a", "timestamp_edge": NOW.isoformat(), "payload": []},  # payload not obj
    "not-a-dict",
])
def test_validation_rejects_malformed(bad):
    assert validate_reading(bad) is not None


# --- task 12: dedup -----------------------------------------------------------

def test_idempotency_key_uses_sequence():
    k = idempotency_key("agent1", reading(asset="m", seq=5))
    assert k == "agent1:m:5"


def test_dedup_cache_detects_repeat():
    c = DedupCache(ttl_seconds=100)
    assert c.seen("k1", now=0.0) is False
    assert c.seen("k1", now=1.0) is True


# --- task 13: sequence --------------------------------------------------------

def test_sequence_ok_gap_reorder():
    s = SequenceTracker()
    assert s.observe("a", "m", 1) == "ok"
    assert s.observe("a", "m", 2) == "ok"
    assert s.observe("a", "m", 5) == "gap"      # skipped 3,4
    assert s.observe("a", "m", 4) == "reorder"  # arrives late


# --- task 14: backpressure ----------------------------------------------------

def test_token_bucket_limits_then_refills():
    b = TokenBucket(rate_per_sec=10, burst=10)
    assert b.allow("a", cost=10, now=0.0) is True   # drains bucket
    assert b.allow("a", cost=1, now=0.0) is False    # empty
    assert b.allow("a", cost=5, now=1.0) is True     # +10 refilled, take 5


def test_gateway_rate_limits_oversized_burst():
    gw = EdgeIngestGateway(rate_per_sec=1, burst=3)
    with pytest.raises(RateLimited):
        gw.ingest("agent1", [reading(seq=i) for i in range(1, 11)], now=NOW)


# --- task 15 + orchestration --------------------------------------------------

def test_ingest_end_to_end_counts():
    quarantined = []
    gw = EdgeIngestGateway(
        rate_per_sec=1000, burst=1000,
        quarantine_sink=lambda aid, r, reason: quarantined.append((r, reason)),
    )
    batch = [
        reading(asset="m", seq=1),
        reading(asset="m", seq=1),          # duplicate -> deduped
        reading(asset="m", seq=2),
        {"asset_id": "m", "payload": {}},   # malformed (no ts) -> quarantined
    ]
    res = gw.ingest("agent1", batch, now=NOW)
    assert res.summary["accepted"] == 2
    assert res.summary["deduped"] == 1
    assert res.summary["quarantined"] == 1
    assert len(quarantined) == 1


# --- Redpanda handoff (audit FIX #2) -------------------------------------------

class _FakeProducer:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []
        self.started = False

    async def start(self):
        if self.fail == "start":
            raise ConnectionError("broker down")
        self.started = True

    async def send_and_wait(self, topic, value):
        if self.fail == "send":
            raise ConnectionError("broker died mid-send")
        self.sent.append((topic, value))


def test_forwarder_publishes_to_org_asset_topics():
    import asyncio
    from app.services.edge_ingest import RedpandaForwarder

    producer = _FakeProducer()
    fw = RedpandaForwarder(producer_factory=lambda: producer)
    sent = asyncio.run(fw.forward("org-1", [
        reading(asset="asset-a", seq=1), reading(asset="asset-b", seq=1),
    ]))
    assert sent == 2
    topics = [t for t, _ in producer.sent]
    assert topics == ["telemetry.org-1.asset-a", "telemetry.org-1.asset-b"]
    assert fw.forwarded == 2 and fw.dropped == 0


def test_forwarder_circuit_opens_when_broker_unreachable():
    import asyncio
    from app.services.edge_ingest import RedpandaForwarder

    fw = RedpandaForwarder(producer_factory=lambda: _FakeProducer(fail="start"),
                           retry_seconds=60)
    sent = asyncio.run(fw.forward("org-1", [reading(seq=1), reading(seq=2)]))
    assert sent == 0 and fw.dropped == 2
    # Circuit open: second call drops immediately without re-connecting.
    sent = asyncio.run(fw.forward("org-1", [reading(seq=3)]))
    assert sent == 0 and fw.dropped == 3


def test_forwarder_mid_send_failure_drops_and_trips():
    import asyncio
    from app.services.edge_ingest import RedpandaForwarder

    fw = RedpandaForwarder(producer_factory=lambda: _FakeProducer(fail="send"))
    sent = asyncio.run(fw.forward("org-1", [reading(seq=1), reading(seq=2)]))
    assert sent == 0
    assert fw.dropped >= 1  # tripped on first failure; batch abandoned to S&F retry


# --- tenant-routed HTTP handler ----------------------------------------------

@pytest.mark.asyncio
async def test_handler_rejects_invalid_org_before_mutating_gateway(monkeypatch):
    from fastapi import HTTPException

    from app.api import edge_ingest as edge_api
    from app.services.edge_ca import AgentPrincipal

    class GatewayMustNotRun:
        def ingest(self, *_args, **_kwargs):
            raise AssertionError("gateway mutated before tenant hint validation")

    monkeypatch.setattr(edge_api, "_gateway", GatewayMustNotRun())
    principal = AgentPrincipal("agent-1", 1, NOW + timedelta(days=1))

    with pytest.raises(HTTPException) as rejected:
        await edge_api.ingest_batch(
            edge_api.IngestBatch(readings=[reading(asset="owned")]),
            principal,
            "not-a-uuid",
        )

    assert rejected.value.status_code == 400


@pytest.mark.asyncio
async def test_handler_forwards_assets_owned_by_certificate_agent(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from uuid import uuid4

    from app.api import edge_ingest as edge_api
    from app.services.edge_ca import AgentPrincipal
    from app.services.edge_ingest import IngestResult

    organization_id = uuid4()
    asset_id = uuid4()
    accepted = [reading(asset=str(asset_id), seq=1)]

    class StubGateway:
        def ingest(self, agent_id, readings):
            assert agent_id == "agent-1"
            assert readings == accepted
            return IngestResult(accepted=list(readings))

    @asynccontextmanager
    async def scoped_session(routed_org):
        assert routed_org == organization_id
        yield object()

    ownership_checks = []

    async def owned_assets(_db, asset_ids, routed_org, agent_id):
        ownership_checks.append((asset_ids, routed_org, agent_id))
        return {str(value) for value in asset_ids}

    class StubForwarder:
        def __init__(self):
            self.calls = []

        async def forward(self, org, readings):
            self.calls.append((org, readings))
            return len(readings)

    forwarder = StubForwarder()
    monkeypatch.setattr(edge_api, "_gateway", StubGateway())
    monkeypatch.setattr(edge_api, "tenant_session", scoped_session)
    monkeypatch.setattr(edge_api, "_owned_asset_ids", owned_assets)
    monkeypatch.setattr(edge_api, "_forwarder", forwarder)

    summary = await edge_api.ingest_batch(
        edge_api.IngestBatch(readings=accepted),
        AgentPrincipal("agent-1", 1, NOW + timedelta(days=1)),
        str(organization_id),
    )
    await asyncio.sleep(0)

    assert summary.accepted == 1
    assert ownership_checks == [
        ({asset_id}, organization_id, "agent-1"),
    ]
    assert forwarder.calls == [(str(organization_id), accepted)]


@pytest.mark.asyncio
async def test_handler_rejects_unowned_asset_before_mutating_gateway(monkeypatch):
    from contextlib import asynccontextmanager
    from uuid import uuid4

    from fastapi import HTTPException

    from app.api import edge_ingest as edge_api
    from app.services.edge_ca import AgentPrincipal

    organization_id = uuid4()
    asset_id = uuid4()

    class GatewayMustNotRun:
        def ingest(self, *_args, **_kwargs):
            raise AssertionError("gateway mutated before asset ownership validation")

    @asynccontextmanager
    async def scoped_session(_organization_id):
        yield object()

    async def owns_nothing(*_args):
        return set()

    monkeypatch.setattr(edge_api, "_gateway", GatewayMustNotRun())
    monkeypatch.setattr(edge_api, "tenant_session", scoped_session)
    monkeypatch.setattr(edge_api, "_owned_asset_ids", owns_nothing)

    with pytest.raises(HTTPException) as rejected:
        await edge_api.ingest_batch(
            edge_api.IngestBatch(readings=[reading(asset=str(asset_id))]),
            AgentPrincipal("agent-1", 1, NOW + timedelta(days=1)),
            str(organization_id),
        )

    assert rejected.value.status_code == 403
