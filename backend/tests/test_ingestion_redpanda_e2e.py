"""Redpanda-to-TimescaleDB telemetry ingestion integration coverage."""

from __future__ import annotations

import asyncio
import json
import os
import tarfile
import time
from datetime import datetime, timezone
from io import BytesIO
from textwrap import dedent
from uuid import uuid4

import pytest


# _RedpandaContainer and the redpanda_container / redpanda_bootstrap_server
# fixtures now live in conftest.py, SESSION-scoped and shared with the other
# Kafka e2e modules. They used to be duplicated per module, which started
# several brokers in one run and made these tests look flaky.

def _admin_async_url(sync_url: str) -> str:
    return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _seed_asset(admin_sync_url: str, seeded_orgs: dict) -> str:
    import psycopg2

    asset_type_id = str(uuid4())
    asset_id = str(uuid4())
    suffix = uuid4().hex[:8]
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (asset_type_id, f"IngestionType-{suffix}", "integration"),
            )
            cur.execute(
                """
                INSERT INTO assets (
                    id,
                    organization_id,
                    workcell_id,
                    asset_type_id,
                    name
                ) VALUES (%s, %s, %s, %s, %s);
                """,
                (
                    asset_id,
                    str(seeded_orgs["org_a_id"]),
                    str(seeded_orgs["workcell_a_id"]),
                    asset_type_id,
                    f"IngestionAsset-{suffix}",
                ),
            )
    finally:
        conn.close()
    return asset_id


def _fetch_ingested_rows(
    admin_sync_url: str, asset_id: str, recorded_at: datetime
) -> list[tuple]:
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT metric_name, value, unit, packml_state, metadata, sequence_num
                FROM telemetry
                WHERE asset_id = %s AND time = %s
                ORDER BY metric_name;
                """,
                (asset_id, recorded_at),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _fetch_asset_state(admin_sync_url: str, asset_id: str) -> tuple:
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT last_seen, current_packml_state
                FROM assets
                WHERE id = %s;
                """,
                (asset_id,),
            )
            return cur.fetchone()
    finally:
        conn.close()


async def _wait_for_rows(
    admin_sync_url: str,
    asset_id: str,
    recorded_at: datetime,
    expected_count: int,
    timeout_seconds: float = 15,
) -> list[tuple]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        rows = _fetch_ingested_rows(admin_sync_url, asset_id, recorded_at)
        if len(rows) == expected_count:
            return rows
        await asyncio.sleep(0.2)
    return _fetch_ingested_rows(admin_sync_url, asset_id, recorded_at)


def test_data_shedding_accepts_timezone_aware_timestamp():
    from app.services.data_shedding import DataSheddingManager

    manager = DataSheddingManager()
    assert manager.should_shed("temperature", datetime.now(timezone.utc)) is False


@pytest.mark.asyncio
async def test_redpanda_telemetry_reaches_database_and_authenticated_api(
    monkeypatch,
    redpanda_bootstrap_server,
    admin_sync_url,
    seeded_orgs,
    client_a,
):
    from aiokafka import AIOKafkaProducer
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.workers import ingestion as ingestion_module

    asset_id = _seed_asset(admin_sync_url, seeded_orgs)
    recorded_at = datetime.now(timezone.utc).replace(microsecond=0)
    sequence_num = int(recorded_at.timestamp() * 1000)
    payload = {
        "telemetry": {
            "temperature": 42.5,
            "speed": 120,
        },
        "source": "redpanda-e2e",
    }
    message = {
        "timestamp_edge": recorded_at.isoformat().replace("+00:00", "Z"),
        "asset_id": asset_id,
        "packml_state": "Execute",
        "payload": payload,
        "sequence_num": sequence_num,
    }
    topic = f"telemetry.{seeded_orgs['org_a_id']}.{asset_id}"

    test_engine = create_async_engine(_admin_async_url(admin_sync_url), future=True)
    test_session_maker = async_sessionmaker(
        test_engine, expire_on_commit=False, autoflush=False
    )
    monkeypatch.setattr(ingestion_module, "AsyncSessionLocal", test_session_maker)

    async def _no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(
        ingestion_module.websocket_manager, "publish_telemetry", _no_op
    )
    monkeypatch.setattr(
        ingestion_module.oee_calculator, "process_telemetry", _no_op
    )

    producer = AIOKafkaProducer(
        bootstrap_servers=redpanda_bootstrap_server,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    await producer.start()
    try:
        await producer.send_and_wait(topic, message)
    finally:
        await producer.stop()

    worker = ingestion_module.IngestionWorker()
    worker.broker_url = redpanda_bootstrap_server
    worker_task = asyncio.create_task(worker.start())
    try:
        rows = await _wait_for_rows(
            admin_sync_url,
            asset_id,
            recorded_at,
            expected_count=2,
        )
    finally:
        await worker.stop()
        await asyncio.wait_for(worker_task, timeout=5)
        await test_engine.dispose()

    assert rows == [
        ("speed", 120, "mm/s", "Execute", payload, sequence_num),
        ("temperature", 42.5, "°C", "Execute", payload, sequence_num),
    ]

    last_seen, current_state = _fetch_asset_state(admin_sync_url, asset_id)
    assert last_seen == recorded_at
    assert current_state == "Execute"

    response = await client_a.get(
        f"/api/v1/telemetry/{asset_id}/latest",
        params={"metric_name": "temperature"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "asset_id": asset_id,
        "timestamp": recorded_at.isoformat(),
        "metric_name": "temperature",
        "value": 42.5,
        "unit": "°C",
        "packml_state": "Execute",
        "metadata": payload,
    }


def _seed_alarm_rule(
    admin_sync_url: str,
    org_id,
    *,
    metric_name: str,
    threshold: float,
    duration_seconds: int = 0,
    comparator: str = "gt",
    alarm_code: str = "E2E_RULE",
    asset_id: str | None = None,
) -> str:
    """Insert an alarm rule directly (superuser, bypasses RLS)."""
    import psycopg2

    rule_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alarm_rules (
                    id, organization_id, name, metric_name, comparator, threshold,
                    duration_seconds, hysteresis, severity, alarm_code, asset_id,
                    is_enabled
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 'critical', %s, %s, TRUE);
                """,
                (
                    rule_id,
                    str(org_id),
                    f"E2E rule {rule_id[:8]}",
                    metric_name,
                    comparator,
                    threshold,
                    duration_seconds,
                    alarm_code,
                    asset_id,
                ),
            )
    finally:
        conn.close()
    return rule_id


def _fetch_alarms_for_asset(admin_sync_url: str, asset_id: str) -> list[tuple]:
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                -- meta_data, not metadata: migration 040 renamed the column
                -- across tables. The API still exposes it as `metadata` through a
                -- serialization alias, so only raw SQL sees the real name.
                SELECT alarm_code, severity, organization_id, meta_data
                FROM alarms WHERE asset_id = %s ORDER BY occurred_at;
                """,
                (asset_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


async def _wait_for_alarms(
    admin_sync_url: str, asset_id: str, expected: int, timeout_seconds: float = 15
) -> list[tuple]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        rows = _fetch_alarms_for_asset(admin_sync_url, asset_id)
        if len(rows) >= expected:
            return rows
        await asyncio.sleep(0.2)
    return _fetch_alarms_for_asset(admin_sync_url, asset_id)


@pytest.mark.asyncio
async def test_alarm_rule_fires_from_a_consumed_telemetry_message(
    monkeypatch,
    redpanda_bootstrap_server,
    admin_sync_url,
    seeded_orgs,
):
    """A rule must fire from a message that travelled through Redpanda (FS-219).

    The service-level tests prove the SQL loader and the Alarm insert, but nothing
    covered the worker path itself: that _process_telemetry actually calls
    evaluation, that the RLS GUC the worker sets makes the rule SELECT visible,
    and that the raised alarm satisfies the alarms WITH CHECK on the same session
    that wrote the telemetry. Those are three different failure modes, and every
    one of them would present as "rules silently never fire in production".

    The negative half matters as much: a non-breaching metric in the SAME message
    must not raise anything, which is what distinguishes evaluation from "any
    telemetry creates an alarm".
    """
    from aiokafka import AIOKafkaProducer
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.services.alarm_rules import InMemoryBreachStore
    from app.workers import ingestion as ingestion_module

    asset_id = _seed_asset(admin_sync_url, seeded_orgs)
    org_id = seeded_orgs["org_a_id"]

    # Breaching rule on temperature, and a rule on `speed` that must NOT fire.
    _seed_alarm_rule(
        admin_sync_url, org_id, metric_name="temperature", threshold=80.0,
        alarm_code="E2E_TEMP_HIGH", asset_id=asset_id,
    )
    _seed_alarm_rule(
        admin_sync_url, org_id, metric_name="speed", threshold=500.0,
        alarm_code="E2E_SPEED_HIGH", asset_id=asset_id,
    )

    recorded_at = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {"telemetry": {"temperature": 95.0, "speed": 120}, "source": "rule-e2e"}
    message = {
        "timestamp_edge": recorded_at.isoformat().replace("+00:00", "Z"),
        "asset_id": asset_id,
        "packml_state": "Execute",
        "payload": payload,
        "sequence_num": int(recorded_at.timestamp() * 1000),
    }
    topic = f"telemetry.{org_id}.{asset_id}"

    test_engine = create_async_engine(_admin_async_url(admin_sync_url), future=True)
    test_session_maker = async_sessionmaker(
        test_engine, expire_on_commit=False, autoflush=False
    )
    monkeypatch.setattr(ingestion_module, "AsyncSessionLocal", test_session_maker)

    async def _no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(ingestion_module.websocket_manager, "publish_telemetry", _no_op)
    monkeypatch.setattr(ingestion_module.oee_calculator, "process_telemetry", _no_op)

    producer = AIOKafkaProducer(
        bootstrap_servers=redpanda_bootstrap_server,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    await producer.start()
    try:
        await producer.send_and_wait(topic, message)
    finally:
        await producer.stop()

    worker = ingestion_module.IngestionWorker()
    worker.broker_url = redpanda_bootstrap_server
    # Pin the in-memory store: the default factory would build a Redis client from
    # settings.REDIS_URL, which is unreachable here. That path degrades rather than
    # failing (by design), but it would make this assertion depend on a timeout.
    worker._breach_store = InMemoryBreachStore()

    worker_task = asyncio.create_task(worker.start())
    try:
        # Wait on the TELEMETRY rows, not the alarm. Both are written in the same
        # transaction, so their presence means the message is fully processed and
        # the worker is idle — polling for the alarm alone can return while the
        # worker is still mid-message, and stopping it there hangs the shutdown.
        rows = await _wait_for_rows(
            admin_sync_url, asset_id, recorded_at, expected_count=2
        )
        alarms = await _wait_for_alarms(admin_sync_url, asset_id, expected=1)
    finally:
        await worker.stop()
        await asyncio.wait_for(worker_task, timeout=10)
        await test_engine.dispose()

    assert len(rows) == 2, f"telemetry did not land: {rows}"

    codes = [row[0] for row in alarms]
    assert codes == ["E2E_TEMP_HIGH"], (
        f"expected exactly the temperature rule to fire, got {codes}"
    )

    alarm_code, severity, alarm_org, metadata = alarms[0]
    assert severity == "critical"
    # organization_id is NOT NULL with FORCE RLS since migration 046 — if the
    # worker failed to set it the INSERT would have raised, so this also proves
    # the write path is tenant-correct rather than merely succeeding.
    assert str(alarm_org) == str(org_id)
    assert metadata["source"] == "alarm_rule"
    assert metadata["metric_name"] == "temperature"
    assert metadata["value"] == 95.0
    assert metadata["threshold"] == 80.0
