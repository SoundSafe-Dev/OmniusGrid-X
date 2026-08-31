"""A tenant's share of the platform does not grow with its headcount (FS-843).

THE DEFECT. `get_user_id_from_request` keys the rate limiter on the token's `sub`, so
every budget was per person. An organisation with 500 users had 500 buckets and therefore
500x the platform share of a single-user tenant, and **nothing anywhere bounded an
organisation as a whole** — `quota`, `max_assets`, `tenant_limit` and `plan_limit` all
returned zero hits across `backend/app`.

Two consequences, and the second is the one that makes it a design fault rather than a
missing feature:

* The noisiest neighbour is structurally the LARGEST CUSTOMER, because budget is
  proportional to seats sold.
* The only containment lever was throttling one user at a time while the other 499
  carried on, which `docs/runbooks/noisy-tenant.md` had to say out loud.

`tenant_limiter` adds the missing dimension. Both limits apply: the per-user one still
protects a tenant from one runaway client of its own, and the tenant one protects every
other tenant from that organisation in aggregate.

WHAT THIS FILE ASSERTS is the keying, not the counting. Whether `limits` decrements a
counter correctly is that library's business and is tested there; what was wrong here was
which counter a request is billed to, so that is what is pinned.
"""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

import jwt
import pytest

from app.core.config import settings
from app.middleware.rate_limit import (
    get_tenant_key_from_request,
    get_user_id_from_request,
)


def _request(token: str | None = None) -> SimpleNamespace:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host="203.0.113.9"),
        scope={"client": ("203.0.113.9", 1234), "headers": []},
    )


def _token(**claims) -> str:
    return jwt.encode(claims, "irrelevant-for-bucketing", algorithm="HS256")


class TestTheBudgetIsTheTenantsNotTheHeadcounts:
    def test_two_users_of_one_org_share_a_tenant_bucket(self):
        """The whole point. Before this, these two returned different keys at every level
        and the organisation's budget was the sum of its users'."""
        alice = _token(sub="user-alice", org="org-1")
        bob = _token(sub="user-bob", org="org-1")

        assert get_tenant_key_from_request(_request(alice)) == "tenant:org-1"
        assert get_tenant_key_from_request(_request(bob)) == "tenant:org-1"

    def test_they_still_have_separate_user_buckets(self):
        """The tenant limit is a SECOND dimension, not a replacement. If it collapsed the
        per-user buckets too, one user could exhaust the tenant budget and the per-user
        limit would stop protecting a tenant from its own runaway client."""
        alice = _token(sub="user-alice", org="org-1")
        bob = _token(sub="user-bob", org="org-1")

        assert get_user_id_from_request(_request(alice)) != get_user_id_from_request(
            _request(bob)
        )

    def test_two_orgs_do_not_share_a_bucket(self):
        """A tenant cap that throttled unrelated tenants together would be worse than
        none: one customer's burst would page for another's outage."""
        one = _token(sub="user-a", org="org-1")
        two = _token(sub="user-b", org="org-2")

        assert get_tenant_key_from_request(_request(one)) != get_tenant_key_from_request(
            _request(two)
        )


class TestTheFallbackFailsSafeRatherThanShared:
    def test_a_token_without_an_org_claim_falls_back_to_its_user_key(self):
        """Access tokens minted before FS-843 carry no `org`, and they stay valid for
        JWT_ACCESS_TOKEN_EXPIRE_MINUTES after deploy. Such a request is bounded by the
        per-user limit and escapes the tenant cap for that window.

        The alternative — a shared `tenant:unknown` bucket — would throttle every
        unattached user against every other one, so a single old client could deny service
        to unrelated tenants. A bounded gap beats an unbounded blast radius.
        """
        legacy = _token(sub="user-alice")  # no org claim

        key = get_tenant_key_from_request(_request(legacy))
        assert key == get_user_id_from_request(_request(legacy))
        assert not key.startswith("tenant:")

    def test_a_user_with_no_organisation_is_not_pooled_with_other_orphans(self):
        """`org: null` is a real state — invited, not yet attached — and is the same case
        as the legacy token above rather than a separate one."""
        unattached = _token(sub="user-new", org=None)

        assert get_tenant_key_from_request(_request(unattached)) == (
            get_user_id_from_request(_request(unattached))
        )

    def test_an_unparseable_token_does_not_raise(self):
        """A rate limiter that raises on a malformed header turns garbage input into a
        500. It must bucket it somewhere and move on."""
        key = get_tenant_key_from_request(_request("not-a-jwt"))
        assert key  # any stable key will do; it must simply not explode

    def test_an_unauthenticated_request_gets_a_key(self):
        assert get_tenant_key_from_request(_request()).startswith("ip:")


class TestTheTenantLimitIsLargerThanOneUsers:
    def test_a_single_user_cannot_exhaust_their_whole_organisation(self):
        """If the tenant limit were <= the per-user limit, one active user would consume
        the entire organisation's budget and the per-user limit would be unreachable —
        the tenant cap would have replaced the per-user one rather than adding to it.
        """

        # Parsed by `limits` itself rather than by a hand-rolled splitter — a second
        # parser here would be a second thing to get wrong, and it is the library that
        # decides what these strings mean.
        import limits

        def _per_second(value: str) -> float:
            item = limits.parse(value)
            return item.amount / item.GRANULARITY.seconds / item.multiples

        assert _per_second(settings.RATE_LIMIT_PER_TENANT) > _per_second(
            settings.RATE_LIMIT_PER_USER
        ), (
            f"RATE_LIMIT_PER_TENANT ({settings.RATE_LIMIT_PER_TENANT}) is not above "
            f"RATE_LIMIT_PER_USER ({settings.RATE_LIMIT_PER_USER}), so one user exhausts "
            f"the organisation and the per-user limit can never be reached."
        )


class TestBothDimensionsAreWired:
    """A limiter nobody registers does not limit.

    ASSERTED STATICALLY, and the first version of this was not — it set
    `RATE_LIMIT_ENABLED=true` and reloaded `app.core.config` and `app.main` to watch the
    middleware appear. That passed alone and broke **27 unrelated tests** in the full
    suite: reloading the config module rebinds the `settings` singleton, while every
    module that did `from app.core.config import settings` at import time keeps a
    reference to the OLD object. Half the process then reads one settings instance and
    half reads another, and the failures surface far from the cause — signed-URL tests,
    in that run.

    So the wiring is read from the source instead. Slower to write, and it cannot damage
    anything.
    """

    def _main_source(self) -> str:
        return (
            pathlib.Path(__file__).resolve().parents[1] / "app/main.py"
        ).read_text()

    def test_both_middlewares_are_registered(self):
        source = self._main_source()
        for middleware in ("SlowAPIMiddleware", "TenantRateLimitMiddleware"):
            assert f"app.add_middleware({middleware})" in source, (
                f"{middleware} is not registered in main.py, so that dimension of the "
                f"rate limit does not apply to any request."
            )

    def test_the_tenant_limiter_is_on_app_state(self):
        """`TenantRateLimitMiddleware` reads `app.state.tenant_limiter`; without it the
        middleware raises on the first request rather than limiting anything."""
        assert "app.state.tenant_limiter = tenant_limiter" in self._main_source()

    def test_both_are_gated_on_the_same_switch(self):
        """An operator who sets RATE_LIMIT_ENABLED must get BOTH dimensions. If they were
        gated separately, one could be on while the other was silently off, and the
        difference is invisible until a tenant saturates the platform.

        PARSED, NOT SEARCHED. The first version of this took a 1400-character window from
        the `if` and asked whether both calls appeared in it — which still passed when the
        tenant middleware was moved OUT of the block, because it remained inside the
        window. Mutation-testing it is the only reason that was found. Rule 37: the check
        has to distinguish the states it claims to.
        """
        tree = ast.parse(self._main_source())
        gated: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = ast.unparse(node.test)
            if "RATE_LIMIT_ENABLED" not in test:
                continue
            for call in ast.walk(node):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_middleware"
                    and call.args
                    and isinstance(call.args[0], ast.Name)
                ):
                    gated.add(call.args[0].id)

        for middleware in ("SlowAPIMiddleware", "TenantRateLimitMiddleware"):
            assert middleware in gated, (
                f"{middleware} is not registered inside an `if settings.RATE_LIMIT_ENABLED` "
                f"block. Enabling rate limiting would then give an operator one dimension "
                f"and not the other, and the difference is invisible until a tenant "
                f"saturates the platform. Gated: {sorted(gated)}"
            )
