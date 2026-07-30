"""A malformed write must be answered, not crashed on.

`test_realdb_endpoint_smoke.py` walks every GET against a migrated Postgres and asserts none of
them 5xx. Nothing walked the WRITE surface, and the failure mode there is different: a POST with
a body the handler did not expect should come back 422 — FastAPI's own answer for a request that
does not validate — and instead crashes somewhere inside the handler, which the caller sees as a
500 with no indication of what was wrong.

This codebase already treats that distinction as a defect worth naming. `fleet_logistics` has
`_uuid_or_404` ("on Postgres, `WHERE uuid_col = 'not-a-uuid'` is an asyncpg type error → 500. A
malformed id simply matches nothing, so answer the honest 404") and `_iso_or_400` ("parse an
ISO-8601 payload field, answering 400 (not a 500) on garbage"). Both exist because somebody hit
a 500 that should have been a 4xx. Neither is enforced anywhere.

WHY AN EMPTY BODY IS THE RIGHT PROBE. It is the one payload that is valid input to the test and
invalid input to every handler: no ids to collide with, nothing written if a handler wrongly
accepts it, and it exercises exactly the path where a required field is read without being
checked. `payload["name"]` on `{}` is a KeyError, which is a 500; `payload.get("name")` that then
flows into a NOT NULL column is an IntegrityError, which is also a 500. Both should be 422.

WHAT A PASS DOES NOT MEAN. That the endpoint works — only that it fails politely. The bodies
that would exercise real behaviour differ per route and belong in per-endpoint tests, which is
where they are.
"""

from __future__ import annotations

import pytest

from tests.route_walk import http_paths

pytest.importorskip("testcontainers")

#: Routes whose 5xx on an empty body is owned by another lane, mirroring the GET walk's list.
#: Asserted BOTH ways below: a new 5xx outside this list fails, and an entry that starts
#: passing also fails, so the list cannot quietly rot.
#:
#: Do not add to this list to make your own change go green.
KNOWN_LANE_FAILURES: dict[str, str] = {
    "/api/v1/kanban/board/view": (
        "HARSH — writes a default board on read and the INSERT violates the task_boards "
        "policy; the same root cause the GET walk records for /kanban/board"
    ),
    "/api/v1/engines/correlation/integration/initialize-registries": (
        "HARSH — same write-on-read shape against actionable_registries: the INSERT runs on "
        "a session whose tenant GUC is not bound, so the policy rejects it"
    ),
    "/api/v1/engines/correlation/generate": (
        "HARSH — correlation_ai_engine; 500 on an empty scenario body rather than a 422"
    ),
}

#: Paths the walk must not call on itself.
#:
#: THE FIRST VERSION OF THIS FILE PASSED WHILE TESTING NOTHING. `/api/v1/auth/logout` is the
#: FOURTH route in registration order; an empty POST to it succeeds, revokes the caller's
#: session, and every one of the 137 probes after it came back 401 — which the first version
#: counted as acceptable, on the reasoning that a 401 means the walk never reached the handler.
#: 133 of 141 probes were 401. The walk was asserting, over and over, that an unauthenticated
#: request is rejected.
SKIP_EXACT = {
    "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
    # Session-mutating: calling these ends the walk's own authentication.
    "/api/v1/auth/logout",
    "/api/v1/auth/refresh",
    # AGENT-CERTIFICATE AUTH, not user auth. `require_agent` reads a forwarded client
    # certificate, so a 401 for a user's bearer token is the correct answer and not a lost
    # session — which is the only reason 401 is otherwise treated as a failure here.
    "/api/v1/edge/heartbeat",
    "/api/v1/edge/ingest",
    "/api/v1/edge/enroll",
}

#: A status the caller can act on — and NOT 401.
#:
#: `client_a` carries a valid token, so a 401 does not mean "the walk never reached the
#: handler", it means something took the session away. Excluding it is what turns the logout
#: problem above from a silent pass into a loud failure: if a future endpoint revokes the
#: session, every probe after it fails and names itself.
#: 503 is allowed for the same reason the GET walk allows it: an endpoint that depends on
#: infrastructure this harness does not run (Redis, pg_stat_statements) must DEGRADE rather
#: than crash, and reporting that degradation is the correct behaviour, not a defect.
ACCEPTABLE = (frozenset(range(200, 500)) | {503}) - {401}


def _probe_path(path: str, fill: str) -> str:
    return "/".join(
        fill if seg.startswith("{") and seg.endswith("}") else seg
        for seg in path.split("/")
    )


@pytest.mark.asyncio
async def test_no_post_5xxs_on_an_empty_body(app, client_a, seeded_orgs):
    """THE ASSERTION THIS FILE EXISTS FOR."""
    fill = str(seeded_orgs["org_a_id"])
    failures: dict[str, str] = {}
    probed: set[str] = set()

    for path in http_paths(app, "POST", skip=SKIP_EXACT):
        probed.add(path)
        try:
            response = await client_a.post(_probe_path(path, fill), json={})
        except Exception as exc:  # noqa: BLE001 — an exception escaping IS the failure
            failures[path] = f"raised {type(exc).__name__}: {exc}"
            continue
        if response.status_code not in ACCEPTABLE:
            failures[path] = f"{response.status_code}: {response.text[:160]}"

    # NON-VACUITY, and the GET walk needed exactly this: iterating `app.routes` directly sees
    # only the handful of top-level entries because fastapi keeps include_router() results as
    # lazy containers, so the walk probed 2 routes and passed.
    assert len(probed) > 50, f"only {len(probed)} POST routes probed — the walk is not walking"

    # THE WALK MUST STILL BE LOGGED IN. This is the check the first version needed and did not
    # have: it is not enough that the loop ran, the requests have to have been authenticated
    # when they ran. A single endpoint that ends the session turns every later probe into a
    # 401, and a walk that accepts 401 reports success for all of them.
    still_authenticated = await client_a.get("/api/v1/assets/")
    assert still_authenticated.status_code != 401, (
        "the walk lost its own authentication partway through, so an unknown number of probes "
        "never reached a handler. Something it POSTed to revokes the session — add it to "
        "SKIP_EXACT."
    )

    unexpected = {p: d for p, d in failures.items() if p not in KNOWN_LANE_FAILURES}
    assert not unexpected, (
        "these POST endpoints 5xx on an empty body instead of answering 422:\n  "
        + "\n  ".join(f"{p}  ->  {d}" for p, d in sorted(unexpected.items()))
        + "\n\nA required field read without being checked is a 500 the caller cannot act on. "
        "Declare it on the request model, or validate it and raise 400/422."
    )

    fixed = sorted(set(KNOWN_LANE_FAILURES) - set(failures))
    assert not fixed, (
        f"these are in KNOWN_LANE_FAILURES and now pass; remove them: {fixed}"
    )


@pytest.mark.asyncio
async def test_no_patch_5xxs_on_an_empty_body(app, client_a, seeded_orgs):
    """PATCH is the sharper of the two: an update handler is usually written against a body
    that has already been through a create, so the "what if this field is absent" path is the
    one nobody walks."""
    fill = str(seeded_orgs["org_a_id"])
    failures: dict[str, str] = {}
    probed: set[str] = set()

    for path in http_paths(app, "PATCH", skip=SKIP_EXACT):
        probed.add(path)
        try:
            response = await client_a.patch(_probe_path(path, fill), json={})
        except Exception as exc:  # noqa: BLE001
            failures[path] = f"raised {type(exc).__name__}: {exc}"
            continue
        if response.status_code not in ACCEPTABLE:
            failures[path] = f"{response.status_code}: {response.text[:160]}"

    assert len(probed) > 5, f"only {len(probed)} PATCH routes probed"
    assert not failures, (
        "these PATCH endpoints 5xx on an empty body:\n  "
        + "\n  ".join(f"{p}  ->  {d}" for p, d in sorted(failures.items()))
    )
