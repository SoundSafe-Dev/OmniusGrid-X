"""An operator's decision on a recommendation is recorded and servable (FS-567 / FS-568).

**A REJECTION USED TO VANISH.** `reject_recommendation` removed the recommendation from
`pending_recommendations` and appended it nowhere. The only record was a
`queue_discrete_event` to `cloud_gateway` — which is never started (FS-530) — so in practice
the operator's decision was discarded the moment it was made.

That is worse than losing an approval. An approval is visible in its effects; **a rejection is
a decision NOT to act, and the only evidence it ever happened is the record of it.** Without
one the same recommendation returns on the next cycle and the operator rejects it again, with
nothing to say they already did.

`get_recommendation_history` existed with no route in front of it, which is why
`StrategicEngine.tsx` renders an em dash for decision history — and why the method sat in the
definition-level dead-code inventory (FS-529), found from the other direction.

THE PLAN'S PREMISE FOR FS-568 WAS WRONG, AND THE TRUTH WAS WORSE. It said the response model
omits `status`, `approved_at` and `rejected_at`, *"which the engine does set"*. The engine did
not. Those keys went into a cloud-event payload bound for a gateway that never starts, and
never onto the recommendation itself. **Both halves were missing** — so declaring the fields
on the response model alone, as the plan described, would have shipped a permanent
`"pending"` for every recommendation ever decided.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api import engines
from app.services.strategic_engine import (
    CloudStrategicEngine,
    StrategicRecommendation,
)


def _recommendation(rec_id: str = "rec-1") -> StrategicRecommendation:
    return StrategicRecommendation(
        recommendation_id=rec_id,
        asset_id="asset-1",
        recommendation_type="maintenance_window",
        priority=1,
        description="Bring the maintenance window forward",
        expected_impact={"oee_improvement": 0.04},
        confidence=0.81,
        simulation_basis="",
        valid_until=datetime.now(timezone.utc) + timedelta(days=7),
        requires_approval=True,
    )


@pytest.fixture
def engine() -> CloudStrategicEngine:
    """A fresh engine per test — the module global accumulates across a session."""
    return CloudStrategicEngine()


class TestADecisionIsRecordedOnTheRecommendation:
    def test_a_new_recommendation_is_pending(self):
        assert _recommendation().status == "pending", (
            "status defaults to something other than 'pending', so a consumer has to "
            "distinguish 'not decided' from 'field absent'"
        )

    @pytest.mark.asyncio
    async def test_an_approval_records_who_and_when(self, engine):
        rec = _recommendation()
        engine.pending_recommendations.append(rec)

        assert await engine.approve_recommendation("rec-1", "operator-7", "agreed")

        assert rec.status == "approved"
        assert rec.decided_by == "operator-7"
        assert rec.decided_at is not None
        assert rec.decision_note == "agreed"

    @pytest.mark.asyncio
    async def test_a_rejection_records_who_and_why(self, engine):
        rec = _recommendation()
        engine.pending_recommendations.append(rec)

        assert await engine.reject_recommendation("rec-1", "operator-7", "line is booked")

        assert rec.status == "rejected"
        assert rec.decided_by == "operator-7"
        assert rec.decision_note == "line is booked"


class TestARejectionSurvives:
    @pytest.mark.asyncio
    async def test_it_is_in_the_history(self, engine):
        """The defect exactly. Before FS-567 this list was empty after a rejection: the
        recommendation was removed from pending and appended nowhere."""
        rec = _recommendation()
        engine.pending_recommendations.append(rec)
        await engine.reject_recommendation("rec-1", "operator-7", "line is booked")

        history = engine.get_recommendation_history()
        assert [r.recommendation_id for r in history] == ["rec-1"], (
            "a rejected recommendation is not in the history, so the operator's decision "
            "left no trace anywhere — and the same recommendation returns next cycle with "
            "nothing to say it was already refused"
        )
        assert history[0].status == "rejected"

    @pytest.mark.asyncio
    async def test_history_carries_both_outcomes(self, engine):
        """`get_recommendation_history` read `implemented_recommendations`, which holds
        approvals only — so a history of decisions omitted every decision not to act."""
        first, second = _recommendation("rec-1"), _recommendation("rec-2")
        engine.pending_recommendations.extend([first, second])

        await engine.approve_recommendation("rec-1", "op", "yes")
        await engine.reject_recommendation("rec-2", "op", "no")

        statuses = {r.recommendation_id: r.status for r in engine.get_recommendation_history()}
        assert statuses == {"rec-1": "approved", "rec-2": "rejected"}

    @pytest.mark.asyncio
    async def test_a_decided_recommendation_leaves_the_pending_list(self, engine):
        """Recording the decision must not resurrect it as pending — an operator who
        rejected something should not be asked again on the next poll."""
        rec = _recommendation()
        engine.pending_recommendations.append(rec)
        await engine.reject_recommendation("rec-1", "op", "no")

        assert engine.get_pending_recommendations() == []


@pytest.mark.asyncio
class TestTheHistoryIsServable:
    async def test_the_route_exists(self):
        paths = {route.path for route in engines.router.routes}
        assert "/strategic/recommendations/history" in paths, (
            "get_recommendation_history has no route, which is why StrategicEngine renders "
            "an em dash for decision history"
        )

    async def test_it_is_not_shadowed_by_the_id_routes(self):
        """`/history` is a literal segment where `{rec_id}` also matches. FastAPI resolves
        in declaration order, so a `/{rec_id}` route declared first would swallow it and
        the endpoint would 404 or 405 while appearing registered."""
        paths = [route.path for route in engines.router.routes]
        history = paths.index("/strategic/recommendations/history")
        parameterised = [
            i for i, p in enumerate(paths) if p.startswith("/strategic/recommendations/{")
        ]
        assert all(history < i for i in parameterised), (
            "a parameterised recommendation route is declared before /history, which "
            "shadows it"
        )

    async def test_the_response_declares_the_decision_fields(self):
        """FastAPI OMITS an undeclared field rather than erroring, so a value can be set on
        the server and absent from the payload with nothing reporting a problem. That is
        what FS-568 was about — and the fields also have to be SET, which is FS-567."""
        declared = engines.StrategicRecommendationResponse.model_fields
        for field in ("status", "decided_at", "decided_by", "decision_note"):
            assert field in declared, (
                f"{field} is not declared on the response model, so it is deleted on the "
                f"way out however carefully the engine records it"
            )
