"""Every table with an `organization_id` should have a tenant policy. Three do not.

Migrations 011, 033 and 051 each enumerated the tables they covered. That works exactly once:
every table added afterwards starts outside every policy, and nothing says so —
`relrowsecurity` is simply false, which is indistinguishable from a deliberate exemption. That
is how `vehicles` ended up as the only unprotected fleet table (arrived in 025, too late for
011/033, not on 051's list), and it is why the tenant-from-body defect wrote a real
cross-tenant row there while the same defect on thirteen sibling tables merely 500'd.

This guard replaces enumeration with a rule: **a table carrying `organization_id` either has
a FORCEd tenant policy, or it appears below with a reason.** A new table fails the suite the
day it lands rather than the day somebody reads a handler carefully.

THE BASELINE BELOW IS A LIST OF GAPS, NOT A LIST OF APPROVALS. Two entries are genuine
exemptions — `users` and `api_keys` are read before any tenant is known, so a policy keyed on
`app.current_org_id` would lock out authentication itself. The third is a real hole with a
real reason for not being closed in this change, and each says what closing it requires.
Closing one is a migration plus an audit of every query against that table, in the order
migration 051 insists on: application layer first, policy second. Doing them blind
would be reckless — enabling FORCE on `users` without tracing every auth path is how you take
down login.

FORCE MATTERS AS MUCH AS ENABLE. Without it the table owner bypasses the policy, and the
application connects as the owner in several deployments — so `relrowsecurity = true` reads as
protected while the only connection that matters is exempt. `app/api/erp_integrations.py`
already recorded this in a comment: its background sync "appeared to work only because no ERP
table has FORCE ROW LEVEL SECURITY and the dev connection owns them". Those five tables were
the last entries here, and migration 058 closed them.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

#: Tables with an `organization_id` and NO row-level security, with why not.
NO_POLICY: dict[str, str] = {
    "users": (
        "EXEMPT BY NECESSITY. Read during authentication, before any tenant is known — a "
        "policy keyed on app.current_org_id would lock out login itself. Tenant scoping here "
        "is the application's job and always will be."
    ),
    "api_keys": (
        "EXEMPT BY NECESSITY. Same shape as users: a key is looked up to discover which "
        "tenant the caller belongs to, so the lookup cannot be filtered by that tenant."
    ),
    # `notification_subscriptions` and `notification_deliveries` were HERE and are CLOSED by
    # migration 056. Their entries said what closing them required — "a check of the dispatcher,
    # which reads subscriptions from a background task with no request behind it" — and that
    # check found four defects rather than a clean bill: two reads that dropped their filter for
    # a user with no organisation, a DELETE with no organisation clause at all, and a dispatcher
    # that would have delivered one tenant's alarm to another's webhook. All five handlers now
    # take the tenant from `get_tenant_org_id`, and every session (including the dispatcher's
    # two) goes through `core.tenant.tenant_session`, which is what made the policy addable.
    #
    # Removed rather than left in place: this guard's own staleness check named them, and a
    # baseline that still lists a closed gap is one nobody trusts.
    "error_events": (
        "REAL GAP, AND BLOCKED ON A GRAIN CHANGE — not on an audit. This table is keyed on "
        "`fingerprint` ALONE: one row per distinct error for the whole platform, shared by "
        "every tenant that hits the same bug, with `organization_id` naming only the last one "
        "to hit it. A tenant policy over that column would hide errors that genuinely are the "
        "caller's, which is worse than the disclosure it would fix. "
        "test_error_triage_sample_redaction_realdb.py records that finding and the decision it "
        "led to: redact the two payload-bearing fields (message_sample, traceback_sample) "
        "cross-tenant rather than pretend the table is partitioned when it is not. "
        "Closing this gap means repartitioning — primary key (fingerprint, organization_id), "
        "a composite foreign key from error_event_buckets, and the ingestion upsert's "
        "ON CONFLICT and COALESCE rewritten — or a platform-admin role to gate the view on. "
        "The earlier entry said to 'check the ingestion path', which understated it: the path "
        "is fine, the grain is the problem."
    ),
    # `edge_agent_status` was HERE and is CLOSED by migration 057. Its entry said to verify the
    # heartbeat path first, because it ran on AsyncSessionLocal and a FORCE policy would have
    # dropped every write. Verifying it found worse: the heartbeat never wrote organization_id
    # AT ALL, while both read endpoints filter on it — so /admin/collectors was empty for every
    # tenant in every deployment since the endpoint was written. Closing the gap meant giving
    # the agent a tenant (from its certificate, with the CA no longer copying the CSR's subject)
    # before the policy could go on. See test_edge_fleet_tenancy_realdb.py.
}

#: Tables with RLS enabled but NOT forced. The owner bypasses the policy, so this reads as
#: protected and is not — worse than no policy, because it answers the question wrongly.
NO_FORCE: dict[str, str] = {
    # ALL FIVE erp_* tables were HERE and are CLOSED by migration 058. Each entry named its own
    # precondition and they were not the same — the sync path, the mapping registry, the
    # correlation analyzers, the webhook append. Every live writer turned out to bind the GUC
    # already; the three *_data_extraction services and erp_database_replication also write
    # these tables and take their session as a parameter, but nothing imports them.
    #
    # The confirming run nearly did not happen: the two real-Postgres ERP suites skip in full
    # without live Dataverse credentials, so "25 passed" would have confirmed the migration
    # against tests that never ran the code it can break. See
    # test_erp_background_sync_under_force_realdb.py, which stubs the vendor call and is
    # controlled by deleting the _set_tenant_guc call.
}

TENANT_TABLES_SQL = """
    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND EXISTS (
        SELECT 1 FROM information_schema.columns col
        WHERE col.table_schema = 'public'
          AND col.table_name = c.relname
          AND col.column_name = 'organization_id'
      )
"""


def _scan(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(TENANT_TABLES_SQL)
            return {name: (enabled, forced) for name, enabled, forced in cur.fetchall()}
    finally:
        conn.close()


class TestTheScanIsNotVacuous:
    async def test_it_finds_the_tenant_tables(self, admin_sync_url, app):
        """If the query stops matching, every assertion below passes over an empty set — the
        failure mode every guard in this repository has had at least once."""
        found = _scan(admin_sync_url)
        assert len(found) > 40, f"only {len(found)} tables carry organization_id"

    async def test_it_sees_a_table_that_is_protected(self, admin_sync_url, app):
        """`assets` has had ENABLE + FORCE since migration 011. If this reads false, the scan
        is wrong rather than the schema."""
        found = _scan(admin_sync_url)
        assert found.get("assets") == (True, True)

    async def test_it_sees_the_table_that_was_just_fixed(self, admin_sync_url, app):
        found = _scan(admin_sync_url)
        assert found.get("vehicles") == (True, True), "migration 055 should have covered this"


class TestNoNewTableEscapesAPolicy:
    async def test_every_unprotected_table_is_recorded(self, admin_sync_url, app):
        """THE ASSERTION THIS FILE EXISTS FOR. A table added tomorrow with an
        `organization_id` and no policy fails here — which is the whole difference from three
        migrations that each enumerated their targets and left the next arrival uncovered."""
        found = _scan(admin_sync_url)
        unprotected = sorted(t for t, (enabled, _) in found.items() if not enabled)
        undocumented = sorted(set(unprotected) - set(NO_POLICY))
        assert not undocumented, (
            "these tables carry organization_id and have no row-level security, and nothing "
            f"says why: {undocumented}.\n"
            "Either add a policy (application layer first — see migration 051's header), or "
            "add an entry to NO_POLICY saying what closing it requires."
        )

    async def test_every_unforced_table_is_recorded(self, admin_sync_url, app):
        """RLS without FORCE is the more dangerous state: it reads as protected."""
        found = _scan(admin_sync_url)
        unforced = sorted(t for t, (enabled, forced) in found.items() if enabled and not forced)
        undocumented = sorted(set(unforced) - set(NO_FORCE))
        assert not undocumented, (
            "these tables have RLS enabled but not FORCEd, so the owner — which is what the "
            f"application connects as in several deployments — bypasses the policy: {undocumented}"
        )


class TestTheBaselineStaysHonest:
    async def test_no_entry_is_already_fixed(self, admin_sync_url, app):
        """A baseline listing a table that now HAS a policy is stale, and a stale list is one
        nobody trusts. Shrinking is the good direction, so this reports rather than blocks."""
        found = _scan(admin_sync_url)
        fixed = [t for t in NO_POLICY if found.get(t, (False, False))[0]]
        fixed += [t for t in NO_FORCE if found.get(t, (False, False))[1]]
        if fixed:
            pytest.skip(f"these are protected now; remove them from the baseline: {sorted(fixed)}")

    async def test_no_entry_names_a_table_that_is_gone(self, admin_sync_url, app):
        found = _scan(admin_sync_url)
        missing = sorted(set(NO_POLICY) | set(NO_FORCE) - set(found))
        missing = [t for t in missing if t not in found]
        assert not missing, f"the baseline names tables that no longer carry organization_id: {missing}"

    def test_every_entry_says_what_closing_it_requires(self):
        """An entry reading "TODO" is a gap with extra steps. Two of these are permanent
        exemptions and say so; the third names the thing to check first."""
        for table, reason in {**NO_POLICY, **NO_FORCE}.items():
            assert len(reason) > 60, f"{table}'s reason is too thin to act on: {reason!r}"

    def test_the_permanent_exemptions_are_marked_as_such(self):
        """`users` and `api_keys` cannot be policied — they are read before a tenant is known.
        Everything else on the list is a hole, and the two must not blur together."""
        assert "EXEMPT BY NECESSITY" in NO_POLICY["users"]
        assert "EXEMPT BY NECESSITY" in NO_POLICY["api_keys"]
        real_gaps = [t for t, r in NO_POLICY.items() if "EXEMPT BY NECESSITY" not in r]
        assert len(real_gaps) == 1, (
            f"the count of real gaps changed ({real_gaps}) — if one was closed, remove it; if "
            "one was added, that is a regression this test should not have allowed"
        )
