"""`GET /api/v1/auth/users` must honour the pagination its client already sends.

THE DEFECT. `authApi.getUsers` takes `{ skip, limit }` and types the result
`PaginatedResponse<User>` — `{ items, total, skip, limit, hasMore }`. The handler
declared NO query parameters and returned only `items` and `total`. **FastAPI drops
unknown query parameters silently**, so `skip` and `limit` were discarded without an
error: a caller asking for the first 25 of 300 users received all 300, and read
`hasMore` as `undefined` — falsy — concluding it had seen everything. It had, which is
exactly why nobody noticed; the bug only becomes visible as an organization grows.

`total` was `len(user_list)`, which is right only while the page is always the whole
set. Under real pagination it reports the PAGE size as the total and the caller stops
paging after one request, so it had to change with the same edit.

HOW IT WAS FOUND. Not by reading this file. `test_frontend_query_params_are_declared.py`
compares what the frontend sends against what the OpenAPI spec declares, and it could
not see this call because the parameters were passed as a variable (`{ params }`) rather
than an object literal. Teaching it to resolve local variables and typed parameters
surfaced this one immediately — the guard's blind spot was hiding it, not the code.

WHAT IS DELIBERATELY UNCHANGED. `hasMore` is camelCase, matching `isActive` and
`createdAt` in the same payload: `/api/v1/auth` is on the casing seam's never-register
list (`transformRegistry.ts`), so no interceptor rewrites this route and what the
handler writes is what TypeScript reads. Converting it to `has_more` would break the
declared type in the opposite direction.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

EXTRA_USERS = 7


@pytest_asyncio.fixture
async def many_users(admin_sync_url, seeded_orgs):
    """Enough users in org A that a page is smaller than the organization.

    One user per org already exists, so org A ends with EXTRA_USERS + 1.
    """
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    ids = [uuid4() for _ in range(EXTRA_USERS)]
    with conn.cursor() as cur:
        for i, uid in enumerate(ids):
            # The email carries the row's own uuid: `users.email` is UNIQUE across the
            # whole table, so a fixed name collides with the previous test's row the
            # moment a teardown does not run.
            cur.execute(
                "INSERT INTO users (id, email, hashed_password, full_name, role, "
                "is_active, organization_id, created_at) VALUES (%s, %s, 'x', %s, "
                "'viewer', true, %s, NOW() + (%s || ' seconds')::interval)",
                (str(uid), f"pager-{uid.hex[:12]}@test.local", f"Pager {i}",
                 str(seeded_orgs["org_a_id"]), i + 1),
            )
    yield EXTRA_USERS + 1
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM users WHERE id = ANY(%s::uuid[])", ([str(i) for i in ids],)
        )
    conn.close()


class TestTheSetupIsReal:
    """If the organization fits in one page, every assertion below passes without
    pagination existing at all."""

    async def test_the_org_has_more_users_than_a_page(self, client_a, many_users):
        body = (await client_a.get("/api/v1/auth/users", params={"limit": 3})).json()
        assert body["total"] > 3, (
            f"org A has only {body['total']} users; a limit of 3 cannot be shown to "
            f"do anything"
        )


class TestThePageIsHonoured:
    async def test_limit_bounds_the_page(self, client_a, many_users):
        """THE ASSERTION THIS FILE EXISTS FOR. Before the fix this returned every user
        in the organization with a 200."""
        body = (await client_a.get("/api/v1/auth/users", params={"limit": 3})).json()
        assert len(body["items"]) == 3, (
            f"asked for 3 users, got {len(body['items'])} — `limit` is being ignored, "
            f"which FastAPI does silently for a parameter the handler never declared"
        )

    async def test_skip_advances_the_page(self, client_a, many_users):
        first = (await client_a.get("/api/v1/auth/users", params={"limit": 3})).json()
        second = (
            await client_a.get("/api/v1/auth/users", params={"skip": 3, "limit": 3})
        ).json()
        assert len(second["items"]) == 3
        overlap = {u["id"] for u in first["items"]} & {u["id"] for u in second["items"]}
        assert not overlap, f"page 2 repeats {overlap} from page 1; the offset is not applied"

    async def test_paging_covers_everyone_exactly_once(self, client_a, many_users):
        """The property that matters to a caller: pages partition the organization.
        Two rows sharing a `created_at` could otherwise swap between pages, which is
        why the ordering carries an `id` tiebreaker."""
        seen, skip = [], 0
        while True:
            body = (
                await client_a.get("/api/v1/auth/users", params={"skip": skip, "limit": 2})
            ).json()
            seen.extend(u["id"] for u in body["items"])
            if not body["hasMore"]:
                break
            skip += 2
            assert skip < 100, "hasMore never went false; paging does not terminate"
        assert len(seen) == len(set(seen)), "a user appeared on two pages"
        assert len(seen) == many_users, (
            f"walked {len(seen)} users but the org has {many_users}; paging drops rows"
        )


class TestTheEnvelopeMatchesTheDeclaredType:
    """`PaginatedResponse<User>` declares five fields. Three of them were absent, and
    an absent `hasMore` reads as `false` in TypeScript — 'you have seen everything'."""

    async def test_every_declared_field_is_present(self, client_a, many_users):
        body = (await client_a.get("/api/v1/auth/users", params={"limit": 2})).json()
        missing = {"items", "total", "skip", "limit", "hasMore"} - set(body)
        assert not missing, f"PaginatedResponse<User> promises {missing}, absent from the response"

    async def test_total_counts_the_organization_not_the_page(self, client_a, many_users):
        """It was `len(user_list)`. As a paginated field that tells a 300-user
        organization it has 25 users and stops the caller from paging."""
        body = (await client_a.get("/api/v1/auth/users", params={"limit": 2})).json()
        assert body["total"] == many_users, (
            f"total={body['total']} with a 2-row page; it is counting the page, not the "
            f"organization ({many_users} users)"
        )

    async def test_has_more_is_true_mid_walk_and_false_at_the_end(self, client_a, many_users):
        early = (await client_a.get("/api/v1/auth/users", params={"limit": 2})).json()
        assert early["hasMore"] is True
        last = (
            await client_a.get("/api/v1/auth/users", params={"limit": 200})
        ).json()
        assert last["hasMore"] is False

    async def test_the_echoed_page_is_the_page_requested(self, client_a, many_users):
        body = (
            await client_a.get("/api/v1/auth/users", params={"skip": 2, "limit": 4})
        ).json()
        assert (body["skip"], body["limit"]) == (2, 4)


class TestTheBoundsAreEnforced:
    async def test_a_negative_skip_is_rejected(self, client_a, many_users):
        assert (await client_a.get("/api/v1/auth/users", params={"skip": -1})).status_code == 422

    async def test_an_unbounded_limit_is_rejected(self, client_a, many_users):
        """Without a ceiling `limit` is a denial-of-service knob on a table that grows
        with the customer."""
        assert (
            await client_a.get("/api/v1/auth/users", params={"limit": 100000})
        ).status_code == 422


class TestTenantScopingSurvivedTheChange:
    """Pagination touched the query. The organization filter is what keeps this from
    being a directory of every customer's staff."""

    async def test_only_the_callers_organization_is_listed(
        self, client_a, seeded_orgs, many_users
    ):
        body = (await client_a.get("/api/v1/auth/users", params={"limit": 200})).json()
        ids = {u["id"] for u in body["items"]}
        assert ids, "no users returned; the assertion below would be vacuous"
        assert str(seeded_orgs["user_a_id"]) in ids, "the caller's own org is not listed"
        assert str(seeded_orgs["user_b_id"]) not in ids, (
            "a user from another organization is listed"
        )
