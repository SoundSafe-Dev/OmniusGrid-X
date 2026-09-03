"""Every (table, column) audited for FS-888..893 stays indexed or registered (FS-894).

WHAT THIS IS, AND WHAT IT IS NOT. FS-888 through FS-893 measured ten tables against the
columns their routes actually filter or order on, closed six real gaps (076-080) and
verified the rest either already had a covering index or is too small/dormant to need one.
This guard is the register that keeps that measurement from rotting: each entry below is
either an index name (checked against a real database) or a reason (checked for being
non-empty, not for being TRUE — a register entry is a claim, not a proof).

**This is not a general sweep of every list route in the app.** Building one that walks
every `.where()`/`.order_by()` call site across ~60 API modules and matches it to a real
schema, without producing a shallow tool that is confident about the wrong thing, is its
own project — the exact risk this sprint's own guards have hit repeatedly (rule 296, rule
297: a check that looks thorough and isn't). What exists here is honest about its scope:
it locks in what was actually measured, and gives future FS-888-shaped work a place to
register into rather than a reason to skip registering at all.
"""
from __future__ import annotations

import psycopg2
import pytest

#: (table, leading column(s) as they'd appear in an indexdef) -> index name that must exist.
INDEXED: dict[tuple[str, str], str] = {
    ("assets", "organization_id, name"): "ix_assets_org_name",
    ("session_data_sources", "session_id"): "ix_session_data_sources_session_id",
    ("session_messages", "session_id"): "ix_session_messages_session_id",
    ("shipments", "organization_id, status"): "ix_shipments_org_status_created",
    ("shipments", "driver_id, scheduled_pickup"): "ix_shipments_driver_scheduled",
    ("yard_trailers", "check_in_at"): "ix_yard_trailers_org_open",
    ("analysis_sessions", "user_id, status"): "ix_analysis_sessions_user_status",
    ("carriers", "organization_id"): "ix_carriers_org_created",
    ("drivers", "organization_id"): "ix_drivers_org_created",
    ("sites", "organization_id"): "uq_sites_org_key",
    ("fleet_tags", "organization_id"): "uq_fleet_tags_org_key",
    ("fleet_groups", "organization_id"): "uq_fleet_groups_org_key",
    ("fleet_cohorts", "organization_id"): "uq_fleet_cohorts_org_name",
}

#: (table, column) -> why no index is needed. Every value must be non-empty; this test does
#: not, and cannot, verify the REASON is still true -- only that nobody deleted it silently.
REGISTERED: dict[tuple[str, str], str] = {
    ("asset_types", "category"): (
        "small global catalogue (FS-888's NOT_TENANT_SCOPED note), not org-scoped, "
        "filtered by category on what is realistically dozens of rows"
    ),
    ("organizations", "id"): "the tenant table itself; PK lookups only, one row per org",
    ("data_retention_config", "table_name"): (
        "keyed by table_name with one config row per data table type -- a few dozen "
        "rows at most, per the module's own comment"
    ),
    ("telemetry_buffers", "*"): (
        "zero references anywhere in backend/app -- no ORM model, no raw SQL. Dormant; "
        "registered for FS-913 rather than indexed"
    ),
    ("permissions", "*"): (
        "zero references anywhere in backend/app. Dormant; registered for FS-913"
    ),
    ("role_permissions", "*"): (
        "zero references anywhere in backend/app. Dormant; registered for FS-913"
    ),
    ("reward_metrics", "*"): (
        "zero references anywhere in backend/app. Dormant; registered for FS-913"
    ),
}


class TestTheRegisterIsNotVacuous:
    def test_both_halves_have_entries(self):
        assert INDEXED, "no indexed entries; this guard is checking nothing"
        assert REGISTERED, "no registered entries; this guard is checking nothing"


class TestEveryIndexedEntryHasARealIndex(object):
    @pytest.mark.parametrize("key", sorted(INDEXED))
    def test_index_exists(self, key, admin_sync_url):
        table, _covers = key
        index_name = INDEXED[key]
        conn = psycopg2.connect(admin_sync_url)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT 1 FROM pg_indexes WHERE tablename = %s AND indexname = %s",
                (table, index_name),
            )
            found = cur.fetchone() is not None
        finally:
            conn.close()
        assert found, (
            f"{index_name} no longer exists on {table} — either it was renamed (update "
            f"this register) or dropped (the column it covered is unindexed again)."
        )


class TestEveryRegisteredExemptionGivesAReason:
    @pytest.mark.parametrize("key", sorted(REGISTERED))
    def test_reason_is_non_empty(self, key):
        reason = REGISTERED[key]
        assert reason and len(reason.strip()) > 10, (
            f"{key} is registered with no real reason — a blank exemption is "
            f"indistinguishable from an unchecked one"
        )
