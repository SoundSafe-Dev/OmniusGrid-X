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


class _RedpandaContainer:
    """Run Redpanda through testcontainers' generic Docker container API."""

    _START_SCRIPT = "/var/lib/redpanda/tc-start.sh"
    _KAFKA_PORT = 9092

    def __init__(self, image: str):
        from testcontainers.core.container import DockerContainer

        self._container = DockerContainer(image, entrypoint="sh")
        self._container.with_exposed_ports(self._KAFKA_PORT)

    def get_bootstrap_server(self) -> str:
        host = self._container.get_container_host_ip()
        port = self._container.get_exposed_port(self._KAFKA_PORT)
        return f"{host}:{port}"

    def start(self):
        from testcontainers.core.waiting_utils import wait_for_logs

        script = self._START_SCRIPT
        self._container.with_command(
            f'-c "while [ ! -f {script} ]; do sleep 0.1; done; sh {script}"'
        )
        self._container.start()

        host = self._container.get_container_host_ip()
        port = self._container.get_exposed_port(self._KAFKA_PORT)
        contents = dedent(
            f"""
            #!/bin/bash
            /usr/bin/rpk redpanda start --mode dev-container --smp 1 --memory 1G \
              --kafka-addr PLAINTEXT://0.0.0.0:29092,OUTSIDE://0.0.0.0:9092 \
              --advertise-kafka-addr \
                PLAINTEXT://127.0.0.1:29092,OUTSIDE://{host}:{port}
            """
        ).strip().encode("utf-8")

        with BytesIO() as archive:
            with tarfile.TarFile(fileobj=archive, mode="w") as tar:
                dirname, basename = os.path.split(script)
                info = tarfile.TarInfo(name=basename)
                info.size = len(contents)
                info.mtime = time.time()
                tar.addfile(info, BytesIO(contents))
            archive.seek(0)
            self._container.get_wrapped_container().put_archive(dirname, archive)

        wait_for_logs(
            self._container,
            r".*Started Kafka API server.*",
            timeout=15,
        )
        return self

    def stop(self):
        self._container.stop()


@pytest.fixture(scope="session")
def redpanda_container():
    """Start an isolated broker so consumer offsets cannot leak between test runs."""
    container = _RedpandaContainer(
        image="docker.redpanda.com/redpandadata/redpanda:v23.3.5"
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def redpanda_bootstrap_server(redpanda_container) -> str:
    return redpanda_container.get_bootstrap_server()


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
