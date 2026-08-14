"""A declared `response_model` is a claim the route can be SERIALISED through it (FS-718).

WHY THIS FILE EXISTS, AND WHAT IT CAUGHT THE SAME HOUR IT WAS WRITTEN.

Twenty correlation routes gained real response models in one change. Two of them were wrong
in the same way — a field annotated from the field's NAME rather than from what the handler
returns — and both would answer **500 to every call**:

  * `GET /capabilities` declared `approval: Dict[str, Any]`. It is a sentence.
  * `POST /evaluations/run` declared `case_result: Dict[str, Any]`. It is a
    `CorrelationEvaluationResult`, and pydantic will not validate a BaseModel as a mapping.

`test_realdb_endpoint_smoke.py` caught the first, because it is a GET. Nothing could catch
the second: that smoke walks GET routes only, which is the right scope for it — a blind POST
walk would create rows. So a whole class of failure (the response model and the handler
disagree) was visible on half the routes and invisible on the other half, and the half it
could not see is where the mutating work lives.

WHAT THIS ASSERTS. That each route below returns a status its own contract allows, and — the
part that matters — never 500. A serialisation failure surfaces as 500 with the model name
nowhere in the response, so a test that accepts "any 2xx or 4xx" still fails on exactly this
defect while staying indifferent to authorisation, validation and empty-state behaviour,
none of which this file is about.

`extra="allow"` DOES NOT PROTECT AGAINST THIS. It tolerates a key the model never declared;
it does not tolerate a declared key whose value is the wrong type. Both defects above were
on declared fields.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def _case() -> dict:
    """A minimal valid evaluation case: one expected match, one candidate that meets it."""
    # `EvidenceReference` is `extra="forbid"` and wants all three parts of the lineage.
    # The first draft of this file invented `record_id`, the route answered 422, and every
    # assertion below still passed — a serialisation smoke that never reaches serialisation
    # (rule 188: a test input the real system can never emit proves nothing about it). The
    # vacuity check at the bottom is what makes that visible.
    left = {"source_id": "src-a", "table_id": "sheet-1", "row_id": "row-1"}
    right = {"source_id": "src-b", "table_id": "sheet-2", "row_id": "row-9"}
    return {
        "case": {
            "case_id": "case-1",
            "name": "smoke",
            "expected_matches": [{"left": left, "right": right}],
        },
        "observed_matches": [
            {"left": left, "right": right, "confidence": 0.9, "is_match": True}
        ],
    }


#: (method, path, body). Every route whose response model was written in FS-718 and which
#: can be reached without uploading a file first. The evidence routes that require real
#: intake rows are covered by the pipeline tests instead — this file is about the models,
#: not the engine.
ROUTES = [
    ("GET", "/api/v1/correlation/evidence/capabilities", None),
    ("GET", "/api/v1/correlation/evidence/quality/latest", None),
    ("GET", "/api/v1/correlation/evidence/vocabulary", None),
    ("GET", "/api/v1/correlation/operations/question-types", None),
    ("POST", "/api/v1/correlation/evidence/evaluations/run", {"fixture": _case()}),
    (
        "POST",
        "/api/v1/correlation/evidence/connectors/postgres/plan",
        {"configuration": {}, "entities": ["orders"]},
    ),
    (
        "POST",
        "/api/v1/correlation/evidence/actions/assess",
        {
            "action": {
                "action_type": "raise_work_order",
                "correlation_confidence": 0.8,
                "data_quality_score": 0.9,
                "risk_score": 10.0,
            }
        },
    ),
    (
        "POST",
        "/api/v1/correlation/evidence/vocabulary",
        {
            "organization_id": "ignored-server-scopes-it",
            "raw_term": "line 4 downtime",
            "canonical_term": "downtime_minutes",
            "kind": "column_alias",
        },
    ),
]


@pytest.mark.parametrize(
    "method,path,body", ROUTES, ids=[f"{m} {p.rsplit('/', 2)[-1]}" for m, p, _ in ROUTES]
)
async def test_the_route_serialises_through_its_response_model(client_a, method, path, body):
    response = await client_a.request(method, path, json=body)
    assert response.status_code != 500, (
        f"{method} {path} returned 500. A response model that disagrees with what the "
        f"handler returns fails exactly here and nowhere else — check the annotation "
        f"against the callee's return type, not against the field's name.\n"
        f"{response.text[:400]}"
    )
    assert response.status_code < 500


async def test_every_route_actually_reaches_serialisation(client_a):
    """EVERY route, not "at least some". A 4xx never reaches the response model, so a body
    this API would reject turns the assertion above into a check that a 422 is not a 500 —
    which it never is. That is not a hypothetical: the first draft of `_case()` invented a
    field name, `POST /evaluations/run` answered 422, and the whole file passed while the
    one route that proves a BaseModel serialises was not being serialised at all.

    A floor of "some routes" could not see it either, which is why this is all of them."""
    statuses = {}
    for method, path, body in ROUTES:
        response = await client_a.request(method, path, json=body)
        statuses[f"{method} {path}"] = response.status_code
    not_ok = {k: v for k, v in statuses.items() if v >= 300}
    assert not not_ok, (
        f"{not_ok} did not answer 2xx, so their response models were never exercised. "
        f"Fix the request body — a rejected request tests nothing about serialisation."
    )
