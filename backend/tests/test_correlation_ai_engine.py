"""Focused unit coverage for Correlation AI's deterministic helper behaviour."""

from pathlib import Path

import pytest

from app.core.config import settings
from app.models.domain_interaction import CrossDomainLink, DomainType
from app.services.correlation_ai_engine import (
    CorrelationAIEngine,
    CorrelationModelUnavailableError,
)


def _link(severity: float) -> CrossDomainLink:
    return CrossDomainLink(
        source_domain=DomainType.PROD,
        target_domain=DomainType.MNT,
        interaction_key="asset-17",
        severity_impact=severity,
    )


def test_helper_risk_score_uses_average_link_severity():
    engine = CorrelationAIEngine()

    assert engine._calculate_risk_score([]) == 50.0
    assert engine._calculate_risk_score([_link(0.2), _link(0.7)]) == 45.0


def test_helper_root_cause_and_kanban_tasks_are_domain_specific():
    engine = CorrelationAIEngine()

    root_cause = engine._simulate_root_cause(
        ["PRODUCTION_OEE", "MAINTENANCE"], [_link(0.8)]
    )
    tasks = engine._generate_kanban_tasks(["PRODUCTION_OEE", "MAINTENANCE"])

    assert "PRODUCTION OEE" in root_cause
    assert "MAINTENANCE" in root_cause
    assert [task["task_type"] for task in tasks] == ["production_job", "custom"]


@pytest.mark.asyncio
async def test_enabled_model_requires_existing_adapter_directory(monkeypatch):
    engine = CorrelationAIEngine()
    missing_adapter = Path("/tmp/omniusgrid-missing-correlation-adapter")
    monkeypatch.setattr(settings, "CORRELATION_ADAPTER_PATH", str(missing_adapter))

    with pytest.raises(CorrelationModelUnavailableError, match="adapter directory does not exist"):
        await engine.ensure_model_ready()

