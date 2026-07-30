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
