"""Tenant retention overrides used by the ingestion data shedder."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.data_shedding import DataSheddingManager


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def execute(self, query, params):
        self.calls += 1
        return _Result(self.rows)


@pytest.mark.asyncio
async def test_tenant_policy_refresh_uses_exact_then_wildcard_and_caches():
    session = _Session(
        [
            {
                "metric_name": "*",
                "ingestion_priority": 2,
                "ingestion_sample_rate": 1.0,
                "max_ingest_age_seconds": 120,
            },
            {
                "metric_name": "vibration",
                "ingestion_priority": 4,
                "ingestion_sample_rate": 0.25,
                "max_ingest_age_seconds": 5,
            },
        ]
    )
    manager = DataSheddingManager()
    await manager.refresh_tenant_policies(session, "org-a")
    await manager.refresh_tenant_policies(session, "org-a")
    assert session.calls == 1

    now = datetime.now(timezone.utc)
    assert manager.should_shed(
        "unknown", now - timedelta(seconds=60), "org-a"
    ) is False
    assert manager.should_shed(
        "vibration", now - timedelta(seconds=10), "org-a"
    ) is True

    manager.invalidate_tenant_policies("org-a")
    await manager.refresh_tenant_policies(session, "org-a")
    assert session.calls == 2


@pytest.mark.asyncio
async def test_tenant_sample_rate_applies_during_load_shedding(monkeypatch):
    session = _Session(
        [
            {
                "metric_name": "vibration",
                "ingestion_priority": 4,
                "ingestion_sample_rate": 0.25,
                "max_ingest_age_seconds": 60,
            }
        ]
    )
    manager = DataSheddingManager()
    await manager.refresh_tenant_policies(session, "org-a")
    manager.update_load_status(
        db_lag_seconds=6,
        queue_depth=15000,
        memory_usage_percent=50,
    )
    monkeypatch.setattr("random.random", lambda: 0.5)

    assert manager.should_shed(
        "vibration", datetime.now(timezone.utc), "org-a"
    ) is True


def test_critical_metrics_cannot_be_downgraded_by_tenant_default():
    manager = DataSheddingManager()
    manager._tenant_priorities[("org-a", "*")] = manager._priorities["debug"]
    manager.update_load_status(
        db_lag_seconds=20,
        queue_depth=100000,
        memory_usage_percent=95,
    )
    assert manager.should_shed(
        "alarm", datetime.now(timezone.utc), "org-a"
    ) is False


@pytest.mark.asyncio
async def test_ingestion_refreshes_and_applies_the_message_tenant(monkeypatch):
    from app.workers import ingestion

    organization_id = str(uuid4())
    asset_id = str(uuid4())
    calls = {"refresh": [], "shed": []}

    class Session:
        def __init__(self):
            self.added = []

        def add(self, row):
            self.added.append(row)

        async def execute(self, query):
            return None

    async def refresh(session, tenant_id):
        calls["refresh"].append(tenant_id)

    def should_shed(metric_name, timestamp, organization_id=None):
        calls["shed"].append((metric_name, organization_id))
        return False

    async def no_op(**kwargs):
        return None

    monkeypatch.setattr(
        ingestion.data_shedder, "refresh_tenant_policies", refresh
    )
    monkeypatch.setattr(ingestion.data_shedder, "should_shed", should_shed)
    monkeypatch.setattr(
        ingestion.websocket_manager, "publish_telemetry", no_op
    )
    monkeypatch.setattr(ingestion.oee_calculator, "process_telemetry", no_op)

    session = Session()
    await ingestion.IngestionWorker()._process_telemetry(
        session,
        asset_id,
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"telemetry": {"temperature": 42.0}},
        },
        organization_id,
    )

    assert calls["refresh"] == [organization_id]
    assert calls["shed"] == [("temperature", organization_id)]
    assert len(session.added) == 1
