"""A reply marked "not an inference" must still say so after a reload (FS-413).

`SessionChatResponse` carries `simulated` / `simulation_reason`, and the chat handler sets
them on all three of its paths: the heuristic substitute used when the correlation model or
its LoRA adapter is not loaded (the deliberate state in this deployment), and the exception
path whose reply is not an analysis at all.

`SessionMessageResponse` — the model behind `GET /nlp/sessions/{id}/messages`,
`/nlp/sessions/chat/history` and `/nlp/sessions/chat/search` — declared NEITHER FIELD, and the three builders
did not read them. So the caveat was attached while the reply was live in the chat and
vanished the instant the transcript was re-fetched. Reload the page and a heuristic answer
came back looking like a real inference.

WHAT MAKES THIS WORSE THAN A MISSING FIELD. The frontend's `SessionMessage` interface has
declared both all along, with a comment explaining why they matter. So the client asked for
them, got `undefined`, and rendered the unlabelled version — the provenance chain was intact
at both ends and broken in the middle, which is the hardest place to notice it.

The data was never lost: the engine writes `simulated` into `analysis`, and `analysis` was
being returned verbatim the whole time. Nobody read it back out.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AnalysisSession, Base, Organization, SessionMessage, User
from tests._sqlite import create_all, sqlite_engine

pytestmark = pytest.mark.asyncio

ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000004")
SESSION_ID = str(uuid.uuid4())
USER_ID = str(uuid.uuid4())


@pytest_asyncio.fixture
async def client():
    engine = sqlite_engine()
    await create_all(engine, Base.metadata, [
        Organization.__table__, User.__table__,
        AnalysisSession.__table__, SessionMessage.__table__,
    ])
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(Organization(id=str(ORG_ID), name="QA", slug="qa-provenance"))
        session.add(User(id=USER_ID, organization_id=str(ORG_ID), email="op@test.local",
                         hashed_password="x" * 60, role="admin", is_active=True))
        session.add(AnalysisSession(id=SESSION_ID, user_id=USER_ID,
                                    organization_id=str(ORG_ID), title="T", status="active"))
        # Three replies: one the engine marked as a heuristic, one it marked as an error
        # fallback, and one genuine inference.
        session.add(SessionMessage(
            id=str(uuid.uuid4()), session_id=SESSION_ID, role="assistant",
            content="heuristic answer",
            analysis={"simulated": True,
                      "simulation_reason": "correlation model not loaded"},
        ))
        session.add(SessionMessage(
            id=str(uuid.uuid4()), session_id=SESSION_ID, role="assistant",
            content="fallback answer",
            analysis={"simulated": True, "simulation_reason": "analysis failed"},
        ))
        session.add(SessionMessage(
            id=str(uuid.uuid4()), session_id=SESSION_ID, role="assistant",
            content="real answer",
            analysis={"predicted_root_cause": "bearing wear"},
        ))
        await session.commit()

    from app.api.auth import get_current_active_user
    from app.core.tenant import get_tenant_db, get_tenant_org_id
    from app.db.database import get_db
    from app.main import app as fastapi_app

    async def _session():
        async with maker() as s:
            yield s

    class _User:
        id = USER_ID
        organization_id = ORG_ID
        role = "admin"
        email = "op@test.local"
        is_active = True

    overrides = dict(fastapi_app.dependency_overrides)
    fastapi_app.dependency_overrides[get_db] = _session
    fastapi_app.dependency_overrides[get_tenant_db] = _session
    fastapi_app.dependency_overrides[get_tenant_org_id] = lambda: ORG_ID
    fastapi_app.dependency_overrides[get_current_active_user] = lambda: _User()
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as c:
        yield c
    fastapi_app.dependency_overrides = overrides


def _by_content(rows):
    return {row["content"]: row for row in rows}


class TestTheTranscriptSaysWhatTheChatSaid:
    async def test_a_heuristic_reply_is_still_labelled_on_reload(self, client):
        response = await client.get(f"/api/v1/nlp/sessions/{SESSION_ID}/messages")
        assert response.status_code == 200, response.text
        rows = _by_content(response.json())

        assert rows["heuristic answer"]["simulated"] is True
        assert rows["heuristic answer"]["simulation_reason"] == "correlation model not loaded"

    async def test_the_error_fallback_keeps_its_own_reason(self, client):
        """Two different reasons, and they must not be collapsed: 'the model is not loaded'
        and 'the analysis threw' send a reader to two different places."""
        rows = _by_content(
            (await client.get(f"/api/v1/nlp/sessions/{SESSION_ID}/messages")).json()
        )
        assert rows["fallback answer"]["simulation_reason"] == "analysis failed"

    async def test_a_genuine_inference_is_not_labelled_simulated(self, client):
        """The other direction matters as much. Marking real output as fabricated would
        train operators to ignore the flag, which costs more than never having it."""
        rows = _by_content(
            (await client.get(f"/api/v1/nlp/sessions/{SESSION_ID}/messages")).json()
        )
        assert rows["real answer"]["simulated"] is False
        assert rows["real answer"]["simulation_reason"] is None


class TestEveryTranscriptSurfaceAgrees:
    """Three endpoints build this model. The defect was in all three, so a test of one
    would have licensed the belief that the class was closed."""

    async def test_chat_history_carries_it(self, client):
        response = await client.get("/api/v1/nlp/sessions/chat/history")
        assert response.status_code == 200, response.text
        rows = _by_content(response.json())
        assert rows["heuristic answer"]["simulated"] is True

    async def test_chat_search_carries_it(self, client):
        response = await client.get("/api/v1/nlp/sessions/chat/search", params={"q": "heuristic"})
        assert response.status_code == 200, response.text
        rows = _by_content(response.json())
        assert rows and all(
            "simulated" in row for row in rows.values()
        ), "search results are messages too, and a caveat that survives only on some "\
           "surfaces is worse than none — a reader learns the flag is unreliable"


class TestTheClientAsksForWhatTheServerSends:
    def test_the_frontend_type_and_the_response_model_agree(self):
        """The frontend declared both fields all along. That is what made this invisible:
        the chain was intact at both ends and broken in the middle."""
        import pathlib

        from app.api.analysis_sessions import SessionMessageResponse

        declared = set(SessionMessageResponse.model_fields)
        assert {"simulated", "simulation_reason"} <= declared

        ts = (pathlib.Path(__file__).resolve().parents[2]
              / "frontend" / "src" / "api" / "analysisSessions.ts").read_text()
        block = ts.split("export interface SessionMessage {")[1].split("}")[0]
        for field in ("simulated", "simulation_reason"):
            assert field in block, (
                f"the frontend's SessionMessage no longer declares `{field}`; if it moved, "
                "update this pairing rather than dropping it"
            )
