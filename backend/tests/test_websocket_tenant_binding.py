"""The realtime channel must authenticate, and take its organisation from the token.

TWO LIVE DEFECTS, both confirmed against the running app before the fix.

**Anyone could subscribe to any organisation, with no token at all.** The handler opened
with `if token:` — so when no token was supplied, `user` stayed None, the code fell
through to the client-supplied `organization_id`, and the connection was accepted as
"anonymous". A caller who could reach the endpoint received another organisation's
telemetry, alarms, state changes and command statuses continuously.

**An authenticated user could name someone else's organisation.** The binding read
"default to the user's organization if not specified", so a supplied value took
PRECEDENCE. Org A's user passing `?organization_id=<org B>` was added to org B's
broadcast set.

WHY NO EXISTING GUARD SAW EITHER. `test_route_auth_walk.py` asserts that every route
rejects an unauthenticated request — and skips `WebSocketRoute` by construction; its own
comment says "skips WebSocketRoute (/ws) + mounts". The rule was enforced everywhere the
walk could reach, and this endpoint sat outside it. Every tenant-scoping sweep in this
codebase has likewise looked at HTTP handlers.

The manager itself was never the problem: `active_connections` is keyed by organisation
and `broadcast_to_organization` only writes to that key. It was told the wrong key.

A mismatched `organization_id` is now REFUSED rather than silently replaced. Substituting
the correct org would leave a caller believing it had subscribed to something it had not.
"""

from __future__ import annotations


def _connect(app, query: str):
    """Attempt a websocket connection; return the first frame or None if refused."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    try:
        with client.websocket_connect(f"/ws{query}") as ws:
            return ws.receive_json()
    except Exception:
        return None


class TestAuthenticationIsRequired:
    def test_no_token_is_refused(self, app, seeded_orgs):
        """THE ASSERTION THIS FILE EXISTS FOR. This connected and streamed another
        organisation's data to an anonymous caller."""
        frame = _connect(app, f"?organization_id={seeded_orgs['org_b_id']}")
        assert frame is None, (
            f"an unauthenticated client was accepted onto the realtime channel: {frame}"
        )

    def test_an_invalid_token_is_refused(self, app, seeded_orgs):
        frame = _connect(
            app, f"?token=not-a-real-token&organization_id={seeded_orgs['org_a_id']}"
        )
        assert frame is None

    def test_no_token_and_no_org_is_refused(self, app):
        assert _connect(app, "") is None


class TestTheOrganisationComesFromTheToken:
    def test_a_valid_token_connects_to_its_own_org(self, app, seeded_orgs, jwt_for_user):
        """Guards the opposite failure: refusing everything would satisfy the
        assertions above and break realtime entirely."""
        frame = _connect(app, f"?token={jwt_for_user['a']}")
        assert frame is not None, "a correctly authenticated client was refused"
        assert frame["type"] == "connection_established"
        assert frame["payload"]["organization_id"] == str(seeded_orgs["org_a_id"])

    def test_naming_another_org_is_refused(self, app, seeded_orgs, jwt_for_user):
        """Org A's user asking for org B. Previously accepted, and the client was added
        to org B's broadcast set."""
        frame = _connect(
            app, f"?token={jwt_for_user['a']}&organization_id={seeded_orgs['org_b_id']}"
        )
        assert frame is None, (
            f"a user was subscribed to another organisation's channel: {frame}"
        )

    def test_naming_your_own_org_is_still_allowed(self, app, seeded_orgs, jwt_for_user):
        """A client that supplies the correct value must not be punished for it — the
        frontend does not send this parameter, but older clients may."""
        frame = _connect(
            app, f"?token={jwt_for_user['a']}&organization_id={seeded_orgs['org_a_id']}"
        )
        assert frame is not None
        assert frame["payload"]["organization_id"] == str(seeded_orgs["org_a_id"])

    def test_the_second_users_token_yields_its_own_org(self, app, seeded_orgs, jwt_for_user):
        """Org B, asserted separately from org A rather than in one test: two websocket
        connections inside a single sync TestClient test collide on the event loop
        ("attached to a different loop"), which is a harness artifact and not a product
        behaviour worth encoding."""
        frame = _connect(app, f"?token={jwt_for_user['b']}")
        assert frame is not None
        assert frame["payload"]["organization_id"] == str(seeded_orgs["org_b_id"])


class TestTheAuthWalkStillCannotSeeThis:
    """Records WHY this file has to exist separately, so nobody deletes it believing
    the route walk covers the websocket."""

    def test_the_route_walk_skips_websocket_routes(self):
        import pathlib

        walk = pathlib.Path(__file__).with_name("test_route_auth_walk.py").read_text()
        assert "skips WebSocketRoute" in walk, (
            "test_route_auth_walk no longer documents skipping websocket routes — if it "
            "now covers them, this file's premise should be re-checked rather than "
            "assumed"
        )
