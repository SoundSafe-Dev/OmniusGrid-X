"""A mutating route must not read some inputs from the query and others from the body (FS-720).

THE MECHANIC. FastAPI decides where a parameter comes from by its TYPE, not by where the
author was thinking of it. A non-Pydantic scalar with no `Body(...)` marker is a QUERY
parameter; a `dict`, a `list` or a model is a BODY parameter. So this signature —

    async def complete_operation(operation_id: UUID, success: bool = True,
                                 metadata: Optional[dict] = None, ...)

publishes `success` in the query string and `metadata` in the JSON body. There is no single
request a client can send that fills both from one document.

WHY THE SPLIT IS WORSE THAN THE ALL-QUERY VERSION, which this repository has already been
bitten by three times. FS-379 (strategic approve/reject), FS-420 and FS-658 (shipment
dispatch and status) were all-query routes: the natural `api.post(url, {field})` was missing
a REQUIRED query parameter, so every call 422'd and the feature visibly never worked once.
Loud, and found by clicking the button.

A split route with a DEFAULTED query parameter fails quietly instead. The body-side field
arrives, so the request succeeds; the query-side field falls back to its default; the server
records something the caller never asked for and answers 200. `POST /operations/{id}/complete`
did exactly this — a client posting `{"success": false}` marked a FAILED operation
**completed**, and its duration and PackML state rollups were computed against that.

WHAT THIS ASSERTS, AND WHAT IT DELIBERATELY DOES NOT. It does not demand that every bare
scalar in the API become a model: `test_required_query_params_are_sent_as_params.py` explains
why 22 all-query routes are left alone and their CLIENTS moved instead — cheaper, and it
crosses no lane boundary. This is the narrower, sharper set: routes that read from BOTH
places at once, where no client can be correct and the failure is silent. The register only
shrinks, and the way off it is one body model, not an entry here.
"""

from __future__ import annotations

import pytest

from app.main import app
from tests._route_tree import http_routes

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

#: Routes that take some parameters in the query and some in the body. **ONLY SHRINKS.**
#: Measured 2026-08-14; `/operations/{id}/complete` was the tenth and is closed.
#:
#: FS-902 (2026-09-03) closed the five that were mine: `/api-keys/generate`,
#: `/gdpr/processing-records`, `/compliance/vendor-assessments` (POST and PUT), and
#: `/data-residency/validate` — each collapsed to one body model. The three that remain
#: are Harsh's; left recorded rather than fixed, per the lane rule.
#:
#: Every entry here is silent by construction — each has at least one DEFAULTED query
#: parameter, so a client posting one JSON body gets a 200 and a value it did not send.
#: They are recorded rather than fixed because each is a published contract change in
#: another lane, and because no client sends a body to any of them today (the frontend
#: agreement is checked by `test_required_query_params_are_sent_as_params.py`). The moment
#: one does, that guard fails and this becomes the reason why.
SPLIT_INPUT: dict[str, str] = {
    "POST /api/v1/engines/tactical/infer":
        "Harsh's lane. `asset_id` in the query, `feature_vector` in the body — an inference "
        "posted as one document is scored against the DEFAULT asset.",
    "POST /api/v1/nlp/correlation/chat":
        "Harsh's lane. `message` is the query parameter and `conversation_history` the body, "
        "so the natural call sends the history and an EMPTY message.",
    "POST /api/v1/nlp/sessions/{session_id}/data/upload":
        "Harsh's lane. `data_type` in the query beside a multipart file; a caller that omits "
        "it gets the default type applied to whatever it uploaded.",
}


def _split_routes() -> dict[str, tuple[list[str], list[str]]]:
    """key -> (query params, body params) for every mutating route that reads from both."""

    def required(param) -> bool:
        checker = getattr(param, "is_required", None)
        if callable(checker):
            return checker()
        info = getattr(param, "field_info", None)
        return info.default is ... if info is not None else True

    found: dict[str, tuple[list[str], list[str]]] = {}
    for route, full, methods in http_routes(app):
        verbs = methods & MUTATING
        dependant = getattr(route, "dependant", None)
        if not verbs or dependant is None:
            continue
        query = [p.name for p in dependant.query_params]
        body = [p.name for p in dependant.body_params]
        if query and body:
            # The QUERY half is narrowed to the parameters that are optional, because those
            # are the ones a body-only client silently loses. A required one 422s instead,
            # which `test_every_registered_route_is_the_silent_kind` keeps out of here.
            found[f"{sorted(verbs)[0]} {full}"] = (
                [p.name for p in dependant.query_params if not required(p)],
                body,
            )
    return found


class TestTheMeasurementIsReal:
    def test_it_finds_body_only_and_query_only_routes_too(self):
        """Vacuity. If `dependant` stopped resolving, every route would look split or none
        would, and both readings are worthless."""
        body_only, query_only = 0, 0
        for route, _full, methods in http_routes(app):
            dependant = getattr(route, "dependant", None)
            if not (methods & MUTATING) or dependant is None:
                continue
            has_q, has_b = bool(dependant.query_params), bool(dependant.body_params)
            body_only += has_b and not has_q
            query_only += has_q and not has_b
        assert body_only > 20, f"only {body_only} body-only mutating routes found"
        assert query_only > 5, f"only {query_only} query-only mutating routes found"

    def test_the_closed_route_takes_one_body(self):
        """`POST /operations/{id}/complete` is the instance this file was written for, and
        it is fixed. If it ever splits again, this fails before the register does."""
        split = _split_routes()
        assert "POST /api/v1/operations/{operation_id}/complete" not in split
        for route, full, _methods in http_routes(app):
            if full.endswith("/operations/{operation_id}/complete"):
                assert not route.dependant.query_params, (
                    "completing an operation reads from the query again; `success` will be "
                    "silently defaulted for any client that posts a body"
                )
                return
        pytest.fail("the route was not found at all")


class TestTheRegisterOnlyShrinks:
    def test_no_new_route_splits_its_input(self):
        new = sorted(set(_split_routes()) - set(SPLIT_INPUT))
        assert not new, (
            f"{new} read some parameters from the query and others from the body. No client "
            f"can send one document that fills both: the body-side fields arrive, the "
            f"query-side fields fall back to their defaults, and the route answers 200 with "
            f"values the caller never sent. Take the whole input as one Pydantic body model."
        )

    def test_the_register_has_not_rotted(self):
        stale = sorted(set(SPLIT_INPUT) - set(_split_routes()))
        assert not stale, (
            f"{stale} no longer split their input — delete the entries rather than leaving "
            f"them to describe code that has moved on"
        )

    @pytest.mark.parametrize("key", sorted(SPLIT_INPUT))
    def test_every_entry_states_what_a_body_only_client_gets(self, key):
        assert len(SPLIT_INPUT[key].strip()) > 40, f"{key} is registered without a reason"

    def test_every_registered_route_is_the_silent_kind(self):
        """The register's claim is that each entry fails QUIETLY — that is what makes it
        worth recording rather than merely fixing. An entry whose query parameters are all
        required would 422 instead, which is a different (and lesser) problem, and it should
        not be filed here."""
        split = _split_routes()
        loud = [k for k in SPLIT_INPUT if k in split and not split[k][0]]
        assert not loud, (
            f"{loud} are registered here but every query parameter is required, so a "
            f"body-only client gets a 422 rather than a wrong value. Move them to "
            f"test_required_query_params_are_sent_as_params.py's population."
        )
