"""An undeclared query parameter is ignored — but it says so (FS-739).

THE DEFECT. `GET /api/v1/assets/?is_activ=true` returns 200 and every asset, active or
not. The filter was mistyped, FastAPI dropped the parameter, and the caller got a
complete, well-formed, plausible answer to a question they did not ask. Same for a client
built against a newer schema than the server is running: the parameter that would have
narrowed the result is discarded and the response looks fine.

WHY IT IS NOT REFUSED, which is the part worth reading. The first fix answered 422, and it
broke fifteen tests that encode a deliberate compatibility guarantee — stated outright in
`test_yard_tenant_scoping_realdb.py`:

    An unknown query parameter must not error either — a client that has not been
    redeployed keeps working.

That is a decision with its reason attached, and a browser holding an open SPA is exactly
the stale client it protects. Overturning it inside an unrelated sweep would be a breaking
API change smuggled in as a defect fix — so the behaviour is unchanged and only the SILENCE
is fixed. Refusing remains available as a deliberate, announced change with a deprecation
window; the case for it is recorded in `docs/engineering/api-contract-gate.md`.

WHAT THIS PINS. That the signal exists at all, in both channels, and that it does not fire
on a valid request. The contract gate still counts these 14 operations as
`AcceptedNegativeData`, correctly — the API does accept input its schema forbids. That is
now a known residue with a written reason rather than an unexamined failure.
"""

from __future__ import annotations

import pytest

from app.middleware.unknown_query_params import ALWAYS_ALLOWED, HEADER

pytestmark = pytest.mark.asyncio


class TestTheSignalFires:
    async def test_a_mistyped_filter_is_reported(self, client_a):
        response = await client_a.get("/api/v1/assets/", params={"is_activ": "true"})
        assert response.status_code == 200, (
            "the parameter must still be IGNORED, not refused — a client that has not "
            "been redeployed keeps working"
        )
        assert response.headers.get(HEADER) == "is_activ", (
            f"a mistyped filter returned {response.status_code} with no {HEADER} header. "
            f"The caller cannot tell that their filter did nothing."
        )

    async def test_several_are_all_reported(self, client_a):
        response = await client_a.get(
            "/api/v1/assets/", params={"is_activ": "true", "serch": "x"}
        )
        assert sorted(response.headers.get(HEADER, "").split(", ")) == ["is_activ", "serch"]

    async def test_the_response_body_is_unchanged(self, client_a):
        """The whole point of warning rather than refusing: same status, same payload."""
        clean = await client_a.get("/api/v1/assets/", params={"limit": 5})
        noisy = await client_a.get(
            "/api/v1/assets/", params={"limit": 5, "is_activ": "true"}
        )
        assert clean.status_code == noisy.status_code == 200
        assert clean.json() == noisy.json()


class TestTheSignalIsQuietWhenItShouldBe:
    """A warning that fires on correct requests is a warning that gets filtered out."""

    async def test_a_valid_request_carries_no_header(self, client_a):
        response = await client_a.get("/api/v1/assets/", params={"limit": 5})
        assert HEADER not in response.headers

    async def test_no_parameters_carries_no_header(self, client_a):
        response = await client_a.get("/api/v1/assets/")
        assert HEADER not in response.headers

    @pytest.mark.parametrize("name", sorted(ALWAYS_ALLOWED))
    async def test_an_allowlisted_parameter_is_quiet(self, client_a, name: str):
        """Cache-busting and the docs OAuth round-trip are not the API's business."""
        response = await client_a.get("/api/v1/assets/", params={name: "1"})
        assert HEADER not in response.headers, (
            f"{name} is allowlisted and still reported"
        )

    async def test_a_route_declaring_no_parameters_is_left_alone(self, client_a):
        """It may be reading `request.query_params` directly, which this cannot see — so
        it must not be told its own parameters are unknown."""
        response = await client_a.get("/api/v1/auth/me", params={"anything": "1"})
        assert response.status_code == 200, response.text[:200]
        assert HEADER not in response.headers


class TestTheWebsocketPathStillWorks:
    """The dependency is global, so it is applied to websocket routes too. Asking for a
    `Request` there cannot be satisfied and refused EVERY `/ws` connection — caught by the
    websocket binding tests, and pinned here beside the reason."""

    async def test_the_dependency_takes_a_connection_not_a_request(self):
        import inspect

        from app.middleware.unknown_query_params import note_unknown_query_params

        # `from __future__ import annotations` in that module makes annotations strings,
        # so compare by name rather than by object — asserting on the object would fail
        # for a reason that has nothing to do with the property under test.
        (param,) = inspect.signature(note_unknown_query_params).parameters.values()
        annotation = getattr(param.annotation, "__name__", param.annotation)
        assert annotation == "HTTPConnection", (
            f"the global dependency takes {annotation!r}. A websocket route cannot "
            f"satisfy a `Request`, and every /ws connection is refused when it does."
        )
