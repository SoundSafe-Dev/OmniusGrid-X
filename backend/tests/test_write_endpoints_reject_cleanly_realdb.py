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

import uuid

import pytest


from tests._realdb import require_testcontainers
from tests._lane_failures import WRITE_FAILURES
from tests.route_walk import http_paths

require_testcontainers()  # FS-808: skips on a laptop, FAILS when REQUIRE_REALDB=1

#: `(method, path)` whose 5xx is owned by another lane, mirroring the GET walk's list.
#:
#: KEYED BY METHOD, and it was not at first. A DELETE-only failure listed by path alone read as
#: "in the list but passing" to the POST walk, whose staleness check then reported it as fixed.
#: One list across four walks needs the method or every entry is stale in three of them.
#: Asserted BOTH ways below: a new 5xx outside this list fails, and an entry that starts
#: passing also fails, so the list cannot quietly rot.
#:
#: Do not add to this list to make your own change go green.
KNOWN_LANE_FAILURES: dict[tuple[str, str], str] = {
    key: entry.reason for key, entry in WRITE_FAILURES.items()
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
    # NEVER PROBED, AND NOT BECAUSE IT MIGHT FAIL. `/api/v1/gdpr/data-delete` takes no path
    # parameter and erases the caller's data on request — a probe that "passes" here has
    # deleted the organisation the rest of the walk is about. It is the one route where the
    # cost of finding out is higher than the finding.
    #
    # COVERED SEPARATELY SINCE FS-358: tests/test_gdpr_data_delete_realdb.py mints a
    # DISPOSABLE user per case and spends it, which is the arrangement a walk cannot have —
    # a walk authenticates once and reuses the session. The skip protects this walk; it was
    # never an excuse for the route to go untested, and for a while it was one.
    "/api/v1/gdpr/data-delete",
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


async def _walk(client, app, method: str, fill: str, send):
    """Probe every route serving `method`, returning `(failures, probed)`."""
    failures: dict[str, str] = {}
    probed: set[str] = set()
    for path in http_paths(app, method, skip=SKIP_EXACT):
        probed.add(path)
        try:
            response = await send(_probe_path(path, fill))
        except Exception as exc:  # noqa: BLE001 — an exception escaping IS the failure
            failures[path] = f"raised {type(exc).__name__}: {exc}"
            continue
        if response.status_code not in ACCEPTABLE:
            failures[path] = f"{response.status_code}: {response.text[:160]}"
    return failures, probed


async def _assert_still_authenticated(client, method: str) -> None:
    """The check the first version of this file needed and did not have.

    It is not enough that the loop ran — the requests have to have been authenticated when
    they ran. One endpoint that ends the session turns every later probe into a 401, and a walk
    that accepts 401 reports success for all of them.
    """
    response = await client.get("/api/v1/assets/")
    assert response.status_code != 401, (
        f"the {method} walk lost its own authentication partway through, so an unknown number "
        "of probes never reached a handler. Something it called revokes the session — add it "
        "to SKIP_EXACT."
    )


@pytest.mark.asyncio
async def test_no_post_5xxs_on_an_empty_body(app, client_a, seeded_orgs):
    """THE ASSERTION THIS FILE EXISTS FOR."""
    METHOD = "POST"
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

    unexpected = {
        p: d for p, d in failures.items() if (METHOD, p) not in KNOWN_LANE_FAILURES
    }
    assert not unexpected, (
        "these POST endpoints 5xx on an empty body instead of answering 422:\n  "
        + "\n  ".join(f"{p}  ->  {d}" for p, d in sorted(unexpected.items()))
        + "\n\nA required field read without being checked is a 500 the caller cannot act on. "
        "Declare it on the request model, or validate it and raise 400/422."
    )

    fixed = sorted(
        path for (method, path) in KNOWN_LANE_FAILURES
        if method == METHOD and path not in failures
    )
    assert not fixed, (
        f"these {METHOD} routes are in KNOWN_LANE_FAILURES and now pass; remove them: {fixed}"
    )


@pytest.mark.asyncio
async def test_no_patch_5xxs_on_an_empty_body(app, client_a, seeded_orgs):
    """PATCH is the sharper of the two: an update handler is usually written against a body
    that has already been through a create, so the "what if this field is absent" path is the
    one nobody walks."""
    METHOD = "PATCH"
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
    await _assert_still_authenticated(client_a, METHOD)

    unexpected = {
        p: d for p, d in failures.items() if (METHOD, p) not in KNOWN_LANE_FAILURES
    }
    assert not unexpected, (
        "these PATCH endpoints 5xx on an empty body:\n  "
        + "\n  ".join(f"{p}  ->  {d}" for p, d in sorted(unexpected.items()))
    )


@pytest.mark.asyncio
async def test_no_put_5xxs_on_an_empty_body(app, client_a, seeded_orgs):
    """PUT completes the write surface. Two of the twenty-five take no path parameter — both
    are settings updates — and the rest are filled with a UUID that matches nothing."""
    METHOD = "PUT"
    fill = str(uuid.uuid4())
    failures, probed = await _walk(
        client_a, app, "PUT", fill, lambda p: client_a.put(p, json={})
    )

    assert len(probed) > 15, f"only {len(probed)} PUT routes probed"
    await _assert_still_authenticated(client_a, "PUT")

    unexpected = {
        p: d for p, d in failures.items() if (METHOD, p) not in KNOWN_LANE_FAILURES
    }
    assert not unexpected, (
        "these PUT endpoints 5xx on an empty body:\n  "
        + "\n  ".join(f"{p}  ->  {d}" for p, d in sorted(unexpected.items()))
    )


@pytest.mark.asyncio
async def test_no_delete_5xxs_on_an_unknown_id(app, client_a, seeded_orgs):
    """A DELETE for a row that does not exist must be a 404, not a crash.

    A FRESH RANDOM UUID, not the seeded organisation id the other walks use. Filling every
    `{...}` with a real id is harmless when the request only reads; on DELETE it is the
    difference between probing and destroying. Nothing in the database has this id, so every
    route here is exercising its not-found path — which is the path most likely to be wrong,
    because the happy path is the one everybody tests.
    """
    METHOD = "DELETE"
    fill = str(uuid.uuid4())
    failures, probed = await _walk(
        client_a, app, "DELETE", fill, lambda p: client_a.delete(p)
    )

    assert len(probed) > 15, f"only {len(probed)} DELETE routes probed"
    await _assert_still_authenticated(client_a, "DELETE")

    unexpected = {
        p: d for p, d in failures.items() if (METHOD, p) not in KNOWN_LANE_FAILURES
    }
    assert not unexpected, (
        "these DELETE endpoints 5xx for an id that does not exist:\n  "
        + "\n  ".join(f"{p}  ->  {d}" for p, d in sorted(unexpected.items()))
        + "\n\nAn unknown id is a 404. A 500 here usually means the id reached the database "
        "unvalidated, or a rowcount of zero was treated as an error."
    )
