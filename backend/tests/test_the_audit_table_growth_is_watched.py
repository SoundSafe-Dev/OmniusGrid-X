"""`audit_logs` grows without bound, and the loop it closes ends in the critical tier (FS-817).

THE SHAPE. `audit_logs` (migration 009) has **no retention policy**. Its sibling
`user_audit_logs` has one — 7 years, GDPR, `005_data_retention.sql:177` — and raw `telemetry`
is dropped after 7 days. `audit_logs` is neither, and being a plain table rather than a
hypertable, `add_retention_policy` does not even apply to it.

The failure is circular and lands on a `critical` alert: unbounded audit growth fills the
volume, the audit write then fails, and `AuditWriteFailing` is severity critical. **The
control that records what happened is the one that ends the system.** Until FS-781 nothing
anywhere alerted on storage exhaustion, so the first symptom would have been the failure.

WHY THIS FILE ASSERTS THE ABSENCE RATHER THAN FIXING IT. Pruning is a decision, not a bug fix,
and it is registered as one in `docs/engineering/open-decisions.md`:

  * migration 069 makes each tenant's rows a hash chain, so deleting the oldest rows leaves
    the earliest survivor's `previous_hash` naming a row that is gone — a verifier must learn
    that a pruned prefix is a root and not a violation, or the integrity control reports a
    permanent violation, which FS-743 established is the same as reporting nothing;
  * OG-AU-004's remediation plans `REVOKE UPDATE, DELETE ON audit_logs`, which a retention job
    contradicts outright — archive-then-delete is the only order that satisfies both;
  * and how long is *required* is a contract question, not an engineering one.

So this file pins the decision open. `test_audit_logs_still_has_no_retention_policy` FAILS the
day someone adds one — which is correct: adding it means the decision was taken, and the entry
in open-decisions.md must then be deleted rather than left to outlive its item. A register that
outlives its entries is the thing this repository keeps rediscovering.

What is *not* a decision is being able to see it coming, and that half is asserted here too.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
MIGRATIONS = REPO / "database" / "migrations"
ALERTS = REPO / "infra" / "prometheus" / "alerts.yml"
QUERIES = REPO / "infra" / "prometheus" / "postgres_queries.yaml"
DECISIONS = REPO / "docs" / "engineering" / "open-decisions.md"

TABLE = "audit_logs"
#: The alerts that make the growth visible while the decision is open.
WATCHERS = ("AuditLogTableGrowingUnbounded", "AuditLogGrowthAccelerating")


def _migration_sql() -> str:
    return "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))


def _alert_names() -> set[str]:
    doc = yaml.safe_load(ALERTS.read_text())
    return {
        rule["alert"]
        for group in doc.get("groups", [])
        for rule in group.get("rules", [])
        if "alert" in rule
    }


class TestTheMeasurementIsReal:
    def test_it_read_the_migrations(self):
        sql = _migration_sql()
        assert len(sql) > 50_000, f"only {len(sql)} chars of SQL read"
        assert "add_retention_policy" in sql, "the retention idiom is gone; this guard is blind"

    def test_a_table_that_does_have_a_policy_is_detected(self):
        """NEGATIVE CONTROL. If the detector cannot see the policy that DOES exist, its
        report that `audit_logs` has none means nothing."""
        sql = _migration_sql()
        assert re.search(r"add_retention_policy\(\s*'telemetry'", sql), (
            "telemetry's retention policy is not visible to this detector — so its verdict "
            "on audit_logs is not evidence of anything"
        )


def test_audit_logs_still_has_no_retention_policy():
    """Pins open-decisions.md #2. Fails when the decision is TAKEN, which is the point."""
    sql = _migration_sql()
    policies = re.findall(r"add_retention_policy\(\s*'([a-z_]+)'", sql)
    drops = re.findall(r"drop_chunks\(\s*'([a-z_]+)'", sql)
    deletes = re.findall(r"DELETE\s+FROM\s+audit_logs", sql, re.I)
    assert TABLE not in policies and TABLE not in drops and not deletes, (
        f"`{TABLE}` now has a retention mechanism (policies={policies}, drops={drops}, "
        f"deletes={len(deletes)}).\n\nThat is good news and this test is how you are being "
        f"told: the open decision in docs/engineering/open-decisions.md has been taken, so "
        f"delete entry #2 and this file. A register that outlives its entries is the thing "
        f"this repository keeps rediscovering.\n\nBefore deleting: confirm the hash-chain "
        f"verifier treats a pruned prefix as a chain root rather than a violation (migration "
        f"069), and that the WORM export runs before any delete — OG-AU-004 plans to REVOKE "
        f"DELETE on this table, which a retention job contradicts."
    )


@pytest.mark.parametrize("alert", WATCHERS)
def test_the_growth_is_watched_while_the_decision_is_open(alert: str):
    assert alert in _alert_names(), (
        f"{alert} is gone. While `{TABLE}` has no retention policy, these alerts are the "
        f"only thing between unbounded growth and a full volume — and a full volume makes "
        f"the audit write fail, which is the `critical` AuditWriteFailing. Removing them "
        f"reinstates a silent path to a critical alert."
    )


def test_the_size_series_the_alerts_read_is_exported():
    """The alerts are worth nothing if nothing produces `pg_table_growth_total_bytes` —
    which is the FS-774 class this sprint spent Wave 1 closing."""
    queries = yaml.safe_load(QUERIES.read_text())
    block = queries.get("pg_table_growth")
    assert block, f"postgres_queries.yaml no longer defines pg_table_growth: {list(queries)}"
    assert TABLE in block["query"], (
        f"the pg_table_growth query no longer selects `{TABLE}`, so both alerts watch a "
        f"series that will never carry that label — inert, and indistinguishable from quiet."
    )
    exported = {list(m)[0] for m in block["metrics"]}
    assert "total_bytes" in exported, exported


def test_the_decision_is_still_registered():
    text = DECISIONS.read_text()
    assert TABLE in text, (
        "open-decisions.md no longer mentions audit_logs. If the decision was taken, this "
        "file should have been deleted with it; if it was not, the register has lost an "
        "entry that is still live."
    )
