"""Any authenticated user could delete any tenant's notification subscription.

    delete(NotificationSubscription).where(NotificationSubscription.id == subscription_id)

No organisation clause. Given an id, one tenant could delete another's subscription — a
cross-tenant destructive write, and `notification_subscriptions` has **no row-level security**
(recorded in `test_every_tenant_table_has_a_policy.py`), so the missing filter was not backed by
a policy either. The endpoint's `rowcount == 0 -> 404` check already existed and was measuring
the wrong thing: it proved a row had been deleted, not that it was yours.

TWO READS LEAKED THE SAME WAY, and this is the more interesting shape. Both list endpoints were
written as:

    org = getattr(current_user, "organization_id", None)
    stmt = select(...)
    if org is not None:
        stmt = stmt.where(... == org)

so a user whose `organization_id` is NULL had the tenant filter **skipped entirely** and read
every organisation's rows. Absence read as unrestricted access — and the exact case this
codebase's own `get_tenant_org_id` exists to refuse: it raises 403 there and its docstring says
why, *"we fail closed rather than fail open"*. A local helper reimplemented the same idea with
the opposite default.

The delivery log is the sharper of the two reads: it carries alarm titles and detail strings
from whatever fired each notification, so an unfiltered read hands one tenant another's alarm
text.

All five handlers now depend on `get_tenant_org_id` and scope unconditionally.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

SUBS = "/api/v1/notifications/subscriptions"
LOG = "/api/v1/notifications/log"


@pytest_asyncio.fixture
async def subscriptions(admin_sync_url, seeded_orgs):
    """One subscription and one delivery row per organisation."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    ids = {}
    with conn.cursor() as cur:
        for key, org in (("a", seeded_orgs["org_a_id"]), ("b", seeded_orgs["org_b_id"])):
            sub_id, del_id = uuid4(), uuid4()
            cur.execute(
                "INSERT INTO notification_subscriptions (id, organization_id, name, channel, "
                "target, min_severity, enabled) VALUES (%s, %s, %s, 'webhook', %s, 'warning', true)",
                (str(sub_id), str(org), f"Sub {key.upper()}", f"https://hooks.example/{key}"),
            )
            cur.execute(
                "INSERT INTO notification_deliveries (id, organization_id, channel, severity, "
                "title, delivered) VALUES (%s, %s, 'webhook', 'critical', %s, true)",
                (str(del_id), str(org), f"Alarm text for org {key.upper()}"),
            )
            ids[key] = {"sub": sub_id, "delivery": del_id}
    yield ids
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM notification_subscriptions WHERE id = ANY(%s::uuid[])",
            ([str(v["sub"]) for v in ids.values()],),
        )
        cur.execute(
            "DELETE FROM notification_deliveries WHERE id = ANY(%s::uuid[])",
            ([str(v["delivery"]) for v in ids.values()],),
        )
    conn.close()


def _still_exists(admin_sync_url, sub_id) -> bool:
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM notification_subscriptions WHERE id = %s", (str(sub_id),)
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


class TestTheDeleteIsScoped:
    async def test_a_tenant_can_delete_its_own(self, client_a, subscriptions, admin_sync_url):
        """The positive control. Without it, "the cross-tenant delete is refused" is satisfied
        by an endpoint that deletes nothing at all."""
        response = await client_a.delete(f"{SUBS}/{subscriptions['a']['sub']}")
        assert response.status_code == 200, response.text
        assert not _still_exists(admin_sync_url, subscriptions["a"]["sub"])

    async def test_another_tenants_subscription_is_not_deleted(
        self, client_a, subscriptions, admin_sync_url
    ):
        """THE ASSERTION THIS FILE EXISTS FOR. Org A asks to delete org B's subscription by
        id. The delete used to match on id alone."""
        response = await client_a.delete(f"{SUBS}/{subscriptions['b']['sub']}")
        assert response.status_code == 404, (
            f"org A deleted org B's subscription (got {response.status_code})"
        )
        assert _still_exists(admin_sync_url, subscriptions["b"]["sub"]), (
            "the row is gone — the delete ran before the scope check, or without one"
        )

    async def test_the_refusal_does_not_confirm_the_row_exists(
        self, client_a, subscriptions
    ):
        """404 and not 403. Whether a given id is live is itself tenant information, and
        "exists but is not yours" tells a caller they have found a real subscription in another
        organisation."""
        real = await client_a.delete(f"{SUBS}/{subscriptions['b']['sub']}")
        absent = await client_a.delete(f"{SUBS}/{uuid4()}")
        assert real.status_code == absent.status_code == 404
        assert real.json().get("detail") == absent.json().get("detail")


class TestTheListsAreScopedUnconditionally:
    async def test_each_tenant_sees_only_its_own_subscriptions(
        self, client_a, client_b, subscriptions
    ):
        a_names = {s["name"] for s in (await client_a.get(SUBS)).json()}
        b_names = {s["name"] for s in (await client_b.get(SUBS)).json()}
        assert "Sub A" in a_names and "Sub B" not in a_names
        assert "Sub B" in b_names and "Sub A" not in b_names

    async def test_the_delivery_log_is_scoped(self, client_a, client_b, subscriptions):
        """The sharper of the two reads: delivery rows carry the alarm title and detail from
        whatever fired the notification, which is the most specific operational text in the
        system."""
        a_titles = {d["title"] for d in (await client_a.get(LOG)).json()}
        b_titles = {d["title"] for d in (await client_b.get(LOG)).json()}
        assert "Alarm text for org A" in a_titles
        assert "Alarm text for org B" not in a_titles
        assert "Alarm text for org B" in b_titles
        assert "Alarm text for org A" not in b_titles


class TestTheSharedSessionHelperResolvesLate:
    """`tenant_session` held a copy of `AsyncSessionLocal` captured at import.

    The test harness rebinds that name PER MODULE — conftest sweeps `sys.modules` for anything
    carrying the attribute — and when `app.core.tenant`'s copy was not among the rebound ones,
    the helper opened a session against the placeholder DATABASE_URL and failed with
    `role "placeholder" does not exist`.

    That stayed invisible for as long as `tenant_session` was only reached through the
    `get_tenant_db` dependency, which the suite overrides wholesale. Moving the notification
    dispatcher onto it — a SERVICE calling it directly — surfaced it immediately, as one failing
    RUL test whose error was swallowed into a warning log.

    Resolving the name on the module at call time removes the class: there is one binding that
    matters and this reads it, rather than holding a copy that may or may not have been patched.
    """

    async def test_it_ignores_a_stale_copy_on_its_own_module(self, app, monkeypatch):
        """THE ASSERTION THIS CLASS EXISTS FOR, and the first version of it was too weak.

        Comparing engines passed under the mutation as well as the fix, because in this test's
        context `app.core.tenant`'s copy happens to be the patched one — the whole defect is
        that whether it is patched varies by test. So the stale copy is SIMULATED: the module
        global is replaced with a maker that raises, and `tenant_session` must still work by
        looking the name up on `app.db.database` at call time.
        """
        from app.core import tenant as tenant_module

        def poisoned():  # pragma: no cover - called only if the helper keeps a copy
            raise AssertionError(
                "tenant_session used its own module-level AsyncSessionLocal instead of "
                "resolving app.db.database's at call time"
            )

        monkeypatch.setattr(tenant_module, "AsyncSessionLocal", poisoned)
        async with tenant_module.tenant_session(uuid4()) as session:
            assert session is not None

    async def test_an_explicit_session_maker_still_wins(self, app):
        """The parameter exists so conftest can inject its own; late resolution must not
        override it."""
        from app.core.tenant import tenant_session
        from app.db import database as database_module

        used = {}

        def maker():
            used["called"] = True
            return database_module.AsyncSessionLocal()

        async with tenant_session(uuid4(), session_maker=maker):
            pass
        assert used.get("called"), "the injected session maker was ignored"


class TestThePolicyIsTheSecondLayer:
    """Migration 056 put a FORCEd policy on both notification tables.

    The application filter is the first line and the tests above cover it. This class covers the
    second, and the distinction matters: for most of this router's life the filter was the ONLY
    protection, and it was conditional — `if org is not None` — so a user with no organisation
    read everything. A policy would have caught that.

    The precondition was the harder half. Every session here used to be an unbound
    `AsyncSessionLocal`, so a FORCEd policy would have emptied every read rather than protecting
    it; all six now go through `core.tenant.tenant_session`, which binds the GUC and re-asserts
    it per transaction.
    """

    async def test_both_tables_are_protected_and_forced(self, admin_sync_url, app):
        """FORCE as well as ENABLE. Without it the owner bypasses the policy, and the
        application connects as the owner in several deployments — so `relrowsecurity = true`
        would read as protected while the only connection that matters is exempt."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = ANY(%s)",
                    (["notification_subscriptions", "notification_deliveries"],),
                )
                rows = {name: (enabled, forced) for name, enabled, forced in cur.fetchall()}
        finally:
            conn.close()
        assert rows.get("notification_subscriptions") == (True, True)
        assert rows.get("notification_deliveries") == (True, True)

    async def test_the_policy_casts_to_uuid(self, admin_sync_url, app):
        """`organization_id` is a real `UUID` column here (022_notifications.sql), unlike the
        varchar columns in 051 and 055 — so the text GUC must be cast. The first version of
        migration 056 omitted the cast and the whole chain failed to build with
        `operator does not exist: uuid = text`. The ORM's `Column(UUIDString())` reads like a
        varchar, which is what led me wrong: the DDL is the authority on a column's type."""
        import psycopg2

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data_type FROM information_schema.columns WHERE table_name = "
                    "'notification_subscriptions' AND column_name = 'organization_id'"
                )
                assert cur.fetchone()[0] == "uuid"
                cur.execute(
                    "SELECT qual FROM pg_policies WHERE tablename = "
                    "'notification_subscriptions' AND policyname = 'tenant_isolation'"
                )
                qual = cur.fetchone()[0]
        finally:
            conn.close()
        assert "::uuid" in qual, f"the policy compares a uuid column to text: {qual}"

    async def test_a_session_bound_to_one_tenant_cannot_see_the_other(
        self, app, admin_sync_url, seeded_orgs, subscriptions
    ):
        """The policy on its own, with NO application filter in the query — which is the only
        way to show the second layer is really there rather than the first one working.

        THE `app` FIXTURE IS REQUIRED, and its absence is not a subtle failure: `tenant_session`
        opens `AsyncSessionLocal`, which only points at the testcontainer once `app` has rebound
        it, so without it this raises `role "placeholder" does not exist`. That is the same trap
        that made three engine tests pass for the wrong reason earlier (rule 23) — it errored
        loudly here only because the assertion is positive; an emptiness assertion would have
        been satisfied by the broken connection."""
        from sqlalchemy import select

        from app.core.tenant import tenant_session
        from app.db.notification_models import NotificationSubscription

        async with tenant_session(seeded_orgs["org_a_id"]) as session:
            names = {
                r.name
                for r in (
                    await session.execute(select(NotificationSubscription))
                ).scalars().all()
            }
        assert "Sub A" in names, "the policy hid the caller's own row"
        assert "Sub B" not in names, (
            "an unfiltered query on a tenant-bound session returned another tenant's row — "
            "the policy is not in force"
        )


class TestTheDispatcherFailsClosed:
    """The worst of the four, and the only LATENT one — worth separating from the rest.

    `_load_rules` had the same conditional filter as the two reads:

        stmt = select(NotificationSubscription).where(enabled == True)
        if org_id is not None:
            stmt = stmt.where(organization_id == org_id)

    A dispatch with no organisation therefore loaded EVERY tenant's subscriptions and
    delivered the event to all of them. That is not a read leak — it is an outbound delivery of
    one tenant's alarm text to another tenant's webhook, Slack channel or mailbox, from the
    server, over the network, with no request behind it to trace.

    NOT LIVE TODAY: both callers pass a real organisation (the test endpoint and the RUL
    notifier), so the None path was unreachable. But `organization_id` is Optional with a None
    default, so the next caller to omit it inherits the fan-out and nothing in the signature
    says so. Fixed by refusing rather than by hoping no one omits it.
    """

    async def test_a_dispatch_with_no_organisation_delivers_nothing(
        self, app, subscriptions
    ):
        """THE ASSERTION THIS CLASS EXISTS FOR. Two tenants have an enabled webhook
        subscription each; a dispatch naming no organisation must match neither."""
        from app.services.notifications import notification_service

        results = await notification_service.dispatch(
            {"severity": "critical", "title": "Fan-out probe", "message": "should reach nobody"}
        )
        assert results == [], (
            f"an event with no organisation matched {len(results)} subscription(s) across "
            "tenants and was delivered to all of them"
        )

    async def test_a_dispatch_naming_one_tenant_reaches_only_that_tenant(
        self, app, subscriptions, seeded_orgs
    ):
        """The positive control, and the property that keeps the refusal honest: a guard that
        returned [] for everything would satisfy the test above and disable notifications."""
        from app.services.notifications import notification_service

        results = await notification_service.dispatch(
            {"severity": "critical", "title": "Scoped probe", "message": "org A only"},
            organization_id=str(seeded_orgs["org_a_id"]),
        )
        targets = {r.get("target") for r in results}
        assert results, "the scoped dispatch matched nothing — the filter is too strict now"
        assert "https://hooks.example/b" not in targets, (
            "org A's event was delivered to org B's webhook"
        )

    async def test_the_helper_is_strict_even_when_called_directly(
        self, app, subscriptions
    ):
        """`dispatch` refuses first, but `_load_rules` is the thing that fans out and is
        reachable on its own. A helper that widens when its argument is missing is one call
        away from doing it again.

        THE `subscriptions` FIXTURE IS LOAD-BEARING, and its absence made the first version of
        this test vacuous: with no rows in the table, `_load_rules(None)` returns `[]` whatever
        the filter does. Restoring the fan-out did not fail it — the mutation check is what
        exposed that, and it is the same emptiness trap this repository keeps hitting. With two
        enabled subscriptions seeded, `[]` now means the filter refused rather than that there
        was nothing to find."""
        from app.services.notifications import notification_service

        # Both fixture subscriptions are enabled, so an unfiltered query returns two.
        assert len(subscriptions) == 2
        rules = await notification_service._load_rules(None)
        assert rules == [], f"_load_rules(None) returned {len(rules)} rules across tenants"


class TestAUserWithNoOrganisationSeesNothing:
    """The shape that made both reads leak: `if org is not None: stmt = stmt.where(...)`.

    A user whose `organization_id` is NULL skipped the filter and read everything. This is
    what `get_tenant_org_id` refuses — 403, and its docstring says "we fail closed rather than
    fail open" — and the local `_org` helper reimplemented the same idea with the opposite
    default. Asserted on the dependency rather than by seeding a broken user, because the
    handlers now delegate the decision to it and that is the thing that must not change.
    """

    async def test_the_dependency_refuses_a_user_without_one(self):
        from types import SimpleNamespace

        from fastapi import HTTPException

        from app.core.tenant import get_tenant_org_id

        # `email` too: the dependency logs the rejected user's identity for observability, so
        # a stub missing it fails on the log line rather than on the assertion — which would
        # have read as the dependency not raising.
        with pytest.raises(HTTPException) as raised:
            await get_tenant_org_id(
                SimpleNamespace(id=uuid4(), email="nobody@test.local", organization_id=None)
            )
        assert raised.value.status_code == 403

    async def test_the_handlers_no_longer_have_a_conditional_filter(self):
        """A source assertion, comments stripped — method rule 37, because the comment
        explaining this defect necessarily contains the pattern it forbids."""
        import pathlib
        import re

        source = pathlib.Path("app/api/notifications.py").read_text()
        source = re.sub(r"#[^\n]*", "", source)
        assert "if org is not None" not in source
        assert "_org(current_user)" not in source


def _target_of(admin_sync_url: str, sub_id) -> str:
    """The stored target, read with the admin connection — the point of a cross-tenant
    update test is what landed in the row, not what the API answered."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT target FROM notification_subscriptions WHERE id = %s", (str(sub_id),)
            )
            row = cur.fetchone()
            return row[0] if row else ""
    finally:
        conn.close()


class TestUpdateIsScopedToTheTenant:
    """The PATCH added for P11 gets the same scoping as the delete above, and needs it
    MORE: a cross-tenant delete destroys a subscription, while a cross-tenant update can
    RETARGET one — pointing another organization's alerts at a webhook of the caller's
    choosing, which turns their incident traffic into your inbox.

    WHAT THESE TESTS ACTUALLY PROVE, established by mutation rather than assumed: removing
    the handler's explicit `organization_id` filter does NOT fail them. That is not a hole
    in the tests, it is defence in depth working — migration 056 gave
    `notification_subscriptions` a row-level-security policy (this file's own header
    predates it and still says the table has none), so the other tenant's row is invisible
    to the SELECT whichever filter the handler writes.

    Both layers are kept deliberately. RLS is the one that cannot be forgotten by a new
    handler; the explicit filter is the one that survives a session opened without the GUC
    — which is exactly how `_check_ingestion` and the FS-704 fleet sweep have been caught
    reading zero rows. A test that could only see one of them would be the weaker claim.
    """

    async def test_a_tenant_can_update_its_own(self, client_a, subscriptions, admin_sync_url):
        """The positive control: without it, "the cross-tenant update is refused" is
        satisfied by an endpoint that updates nothing at all."""
        response = await client_a.patch(
            f"{SUBS}/{subscriptions['a']['sub']}", json={"enabled": False}
        )
        assert response.status_code == 200, response.text
        assert response.json()["enabled"] is False

    async def test_another_tenants_subscription_is_not_retargeted(
        self, client_a, subscriptions, admin_sync_url
    ):
        before = _target_of(admin_sync_url, subscriptions["b"]["sub"])
        response = await client_a.patch(
            f"{SUBS}/{subscriptions['b']['sub']}",
            json={"target": "https://attacker.example.com/collect"},
        )
        assert response.status_code == 404, (
            f"org A retargeted org B's subscription (got {response.status_code})"
        )
        assert _target_of(admin_sync_url, subscriptions["b"]["sub"]) == before, (
            "the row changed — the update ran before the scope check, or without one"
        )

    async def test_a_partial_update_leaves_the_rest_alone(
        self, client_a, subscriptions
    ):
        """PATCH semantics, asserted: `exclude_unset` is what keeps a toggle from
        blanking the fields the form did not send."""
        listed = (await client_a.get(SUBS)).json()
        original = next(
            row for row in listed if row["id"] == str(subscriptions["a"]["sub"])
        )

        response = await client_a.patch(
            f"{SUBS}/{subscriptions['a']['sub']}", json={"enabled": False}
        )
        assert response.status_code == 200, response.text
        updated = response.json()
        assert updated["name"] == original["name"]
        assert updated["target"] == original["target"]
        assert updated["min_severity"] == original["min_severity"]

    async def test_an_unknown_severity_is_refused(self, client_a, subscriptions):
        """The closed set holds on the way in. A severity this server never dispatches
        would be discovered when an alert silently goes nowhere."""
        response = await client_a.patch(
            f"{SUBS}/{subscriptions['a']['sub']}", json={"min_severity": "catastrophic"}
        )
        assert response.status_code == 422, response.text


@pytest_asyncio.fixture
async def owned_asset(admin_sync_url, seeded_orgs):
    """An asset belonging to ORG A, so "another tenant's asset" means a row that genuinely
    exists rather than an id nobody owns — the distinction the whole class turns on, since
    a non-existent id is refused by the foreign key and an existing one is not.

    Local rather than shared with `test_inline_session_tenant_scoping_realdb.py`, which has
    the same fixture: `test_no_two_guards_keep_the_same_list.py` is about REGISTERS that
    two guards must not both curate, and this is a two-row insert. Importing across test
    modules to save it would couple two suites to each other's cleanup order.
    """
    import psycopg2

    ids = {"type": uuid4(), "asset": uuid4()}
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'machine')",
            (str(ids["type"]), f"FS726-{uuid4().hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, asset_type_id, workcell_id, name, is_active) "
            "VALUES (%s, %s, %s, %s, 'FS726 Asset', true)",
            (
                str(ids["asset"]),
                str(seeded_orgs["org_a_id"]),
                str(ids["type"]),
                str(seeded_orgs["workcell_a_id"]),
            ),
        )
    yield ids["asset"]
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM notification_subscriptions WHERE asset_id = %s", (str(ids["asset"]),)
        )
        cur.execute("DELETE FROM assets WHERE id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(ids["type"]),))
    conn.close()


class TestASubscriptionMayOnlyWatchAnAssetYouOwn:
    """The third door into this router, found by carrying FS-724's question across
    (`what proves this id belongs to the caller`) rather than by another leak report.

    `asset_id` was `Optional[str]`, so two things were true at once:

      * `{"asset_id": "nope"}` reached Postgres and came back a **500**, where the contract
        promises a 4xx;
      * a well-formed id belonging to ANOTHER organisation was accepted with a **200**. The
        foreign key is checked below RLS, so the database has no objection.

    The second is quieter than a leak and is the reason it is worth a test rather than a
    shrug: the subscription is real, it belongs to the subscriber, and it can never fire,
    because the alarms it filters for belong to a tenant this subscriber cannot see. **A
    notification rule that cannot fire is worse than no rule** — the operator believes they
    are covered, and nothing anywhere reports the silence.

    THE PATCH IS TESTED SEPARATELY FROM THE POST because it is a second door onto the same
    field: an update can move a subscription onto another organisation's asset just as a
    create can point it there, and fixing only the create would have left the newer route
    reintroducing the older defect.
    """

    BODY = {"name": "n", "channel": "email", "target": "a@b.com", "min_severity": "warning"}

    async def test_a_malformed_asset_is_refused_not_a_crash(self, client_a):
        response = await client_a.post(
            "/api/v1/notifications/subscriptions", json={**self.BODY, "asset_id": "nope"}
        )
        assert response.status_code == 422, (
            f"answered {response.status_code}; a bare `str` lets the value reach Postgres"
        )

    async def test_another_tenants_asset_is_refused(self, client_b, owned_asset):
        response = await client_b.post(
            "/api/v1/notifications/subscriptions",
            json={**self.BODY, "asset_id": str(owned_asset)},
        )
        assert response.status_code == 404, (
            f"org B subscribed to org A's asset and got {response.status_code}. The rule "
            f"would be stored, owned by org B, and permanently silent."
        )

    async def test_a_patch_cannot_move_it_onto_another_tenants_asset(
        self, client_b, owned_asset
    ):
        created = await client_b.post("/api/v1/notifications/subscriptions", json=self.BODY)
        assert created.status_code == 200, created.text[:200]
        response = await client_b.patch(
            f"/api/v1/notifications/subscriptions/{created.json()['id']}",
            json={"asset_id": str(owned_asset)},
        )
        assert response.status_code == 404, response.text[:200]

    async def test_the_owner_can_still_watch_their_own_asset(self, client_a, owned_asset):
        """The denominator. Every assertion above is satisfied by a route that refuses
        every asset."""
        response = await client_a.post(
            "/api/v1/notifications/subscriptions",
            json={**self.BODY, "asset_id": str(owned_asset)},
        )
        assert response.status_code == 200, response.text[:300]

    async def test_a_subscription_without_an_asset_still_works(self, client_a):
        """`asset_id` is optional — an organisation-wide rule is the common case, and
        typing the field must not make it required."""
        response = await client_a.post("/api/v1/notifications/subscriptions", json=self.BODY)
        assert response.status_code == 200, response.text[:300]
