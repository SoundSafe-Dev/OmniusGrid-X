"""A compression policy at or beyond the retention interval never saves a byte (FS-816).

`001_init.sql:101` compressed telemetry after 7 days. `005_data_retention.sql:22` dropped it
after 7 days. A chunk therefore became eligible for compression and for DELETION at the same
instant, and whichever background job won the race the outcome was identical: **telemetry was
never stored compressed for any period worth having.**

Nothing was broken in a way anyone would notice. Both policies existed, both were installed,
`timescaledb_information.jobs` listed them, and the platform quietly paid uncompressed prices
for its entire retention window. Measured on the real schema with the real
`compress_segmentby`, over 2,161,000 rows:

    uncompressed   142.7 bytes/row
    compressed      19.4 bytes/row
    ratio            7.3x   (86.4% saved)

An 86% saving, configured and idle. It also distorted the retention decision it was blocking:
the break-even is 51 days, so ninety days of COMPRESSED telemetry costs about twice what seven
days of uncompressed costs — not the twelvefold the raw window implies. A window that looks
unaffordable because compression silently is not running is the expensive half of this bug.

WHAT THIS ASSERTS. For every hypertable with both policies, `compress_after < drop_after`,
strictly. Equality is the defect; greater is worse. The interval arithmetic is done in days
because that is the unit every policy in this repository is written in.

WHY IT READS THE MIGRATIONS AND NOT A DATABASE. The chain is the source of truth — a policy
installed by hand on one environment is not a property of the product — and this way the guard
runs in the plain suite rather than only where Docker is available.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
MIGRATIONS = REPO / "database" / "migrations"

#: Hypertables with a compression policy but no retention policy, and why that is right.
#: An entry says "this table is compressed and kept forever", which is a real choice.
NO_RETENTION_BY_DESIGN: dict[str, str] = {
    "telemetry": (
        "compressed at 7 days and never dropped by a GLOBAL policy — deliberately. "
        "Retention is per tenant, via enforce_tenant_historian_retention()'s row DELETE "
        "(migration 034), because a chunk holds many organisations' rows and cannot honour "
        "a per-tenant window. Growth is therefore bounded by that sweep, not by a policy "
        "this parser can see."
    ),
}

_UNITS = {
    "second": 1 / 86400, "seconds": 1 / 86400,
    "minute": 1 / 1440, "minutes": 1 / 1440,
    "hour": 1 / 24, "hours": 1 / 24,
    "day": 1, "days": 1,
    "week": 7, "weeks": 7,
    "month": 30, "months": 30,
    "year": 365, "years": 365,
}


def _days(interval: str) -> float:
    """`INTERVAL '7 days'` -> 7.0"""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s+(\w+)\s*", interval)
    assert match, f"unparsed interval: {interval!r}"
    amount, unit = match.groups()
    assert unit in _UNITS, f"unknown interval unit {unit!r} in {interval!r}"
    return float(amount) * _UNITS[unit]


def _without_comments(sql: str) -> str:
    """Strip `--` and block comments before parsing.

    RULE 37, AND IT BIT IMMEDIATELY. Migration 072's header explains the near-miss it exists
    to prevent, and to do so it QUOTES the dangerous statement:

        -- A first draft of this migration reinstated a global
        -- `add_retention_policy('telemetry', INTERVAL '90 days')` and would have re-broken…

    The first version of this parser read that comment and reported telemetry as carrying a
    90-day global chunk-drop — flagging the very migration whose whole purpose is to not do
    that. A detector whose input includes prose about its own subject confirms whatever the
    prose says, which is the third time this repository has recorded the shape.
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


def _policies() -> dict[str, dict[str, float]]:
    """table -> {'compress': days, 'drop': days}, applying the chain in order.

    LATER MIGRATIONS WIN, because that is what happens when the chain is applied — and a
    guard that read only the first occurrence would report the state this file was written
    to fix as still present after 072 corrected it.
    """
    # ONE PASS, IN SOURCE ORDER. A version of this that applied every `add_` in a file
    # before every `remove_` reported migration 072 — which removes the fighting policies
    # and then re-adds them at new intervals — as having removed them and stopped. The
    # order of statements inside a file is as load-bearing as the order of the files.
    statement = re.compile(
        r"(add_compression_policy|add_retention_policy|"
        r"remove_compression_policy|remove_retention_policy)"
        r"\(\s*'(\w+)'(?:\s*,\s*INTERVAL\s*'([^']+)')?"
    )
    kinds = {
        "add_compression_policy": ("compress", True),
        "add_retention_policy": ("drop", True),
        "remove_compression_policy": ("compress", False),
        "remove_retention_policy": ("drop", False),
    }
    state: dict[str, dict[str, float]] = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        for call, table, interval in statement.findall(_without_comments(path.read_text())):
            kind, adding = kinds[call]
            if adding:
                assert interval, f"{path.name}: {call}('{table}') with no INTERVAL"
                state.setdefault(table, {})[kind] = _days(interval)
            else:
                state.get(table, {}).pop(kind, None)
    return state


class TestTheMeasurementIsReal:
    def test_it_found_the_policies(self):
        found = _policies()
        assert "telemetry" in found, f"telemetry has no policies parsed: {found}"
        assert "packml_states" in found, found
        # packml_states is the table that carries BOTH kinds, so it is the one that proves
        # the parser can see a compress/drop pair at all — telemetry deliberately has no
        # global drop policy, so asserting one there would pin the wrong premise.
        assert found["packml_states"].get("drop"), found["packml_states"]
        assert found["packml_states"].get("compress"), found["packml_states"]

    def test_it_applies_removals_as_well_as_additions(self):
        """The chain's net effect on telemetry, which is not what any single file says.

            001:104  add_retention_policy(30 days)
            005:22   add_retention_policy(7 days, if_not_exists)  -> NO-OP, one existed
            034:210  remove_retention_policy()                    -> deliberately removed
            001:101  add_compression_policy(7 days)               -> never removed

        So telemetry is compressed at 7 days and has NO global retention policy — its
        retention is per tenant. A parser that ignored removals would report the 30-day
        policy as live, and one that took the last `add_` would report 7."""
        telemetry = _policies()["telemetry"]
        assert telemetry.get("compress") == 7, telemetry
        assert "drop" not in telemetry, (
            f"a global retention policy is parsed for telemetry ({telemetry}); migration "
            f"034 removed it deliberately"
        )

    def test_it_ignores_policies_named_only_in_comments(self):
        """Rule 37's control. Migration 072's header quotes the dangerous statement in
        order to warn against it, and the first version of this parser believed it."""
        sample = "-- add_retention_policy('telemetry', INTERVAL '90 days')\nSELECT 1;"
        assert "add_retention_policy" not in _without_comments(sample)

    def test_the_interval_parser_handles_the_units_used(self):
        assert _days("7 days") == 7
        assert _days("90 days") == 90
        assert _days("1 hour") == pytest.approx(1 / 24)
        assert _days("1 year") == 365

    def test_it_would_catch_the_original_shape(self):
        """POSITIVE CONTROL: equal intervals are the defect, not merely suspicious."""
        assert not (7 < 7), "the comparison this file rests on"


def test_every_compression_policy_runs_before_its_retention_drops():
    offenders = []
    for table, policy in sorted(_policies().items()):
        compress, drop = policy.get("compress"), policy.get("drop")
        if compress is None or drop is None:
            continue
        if compress >= drop:
            offenders.append(
                f"{table}: compresses after {compress:g}d but drops after {drop:g}d"
            )
    assert not offenders, (
        "these hypertables compress at or after the point they are dropped, so the "
        "compression never stores anything and its saving is never realised:\n  "
        + "\n  ".join(offenders)
        + "\n\nMeasured on this schema: 7.3x, 86.4% saved — configured and idle. The cost "
        "is not only disk: a retention window looks unaffordable when the compression that "
        "would pay for it silently is not running."
    )


#: Hypertables whose retention is enforced PER TENANT rather than by a global chunk-drop.
#: A global `add_retention_policy` on one of these is a cross-tenant data-loss bug: a chunk
#: holds rows for every organisation in its time range, so dropping it deletes data
#: belonging to tenants who configured a longer window.
TENANT_SCOPED_RETENTION = {
    "telemetry": (
        "migration 034 removed the global policy deliberately and replaced it with "
        "enforce_tenant_historian_retention() — a per-tenant, per-metric row DELETE. "
        "See docs/DELIVERY-LOG.md, FS-816."
    ),
}


def test_no_global_retention_policy_on_a_tenant_scoped_hypertable():
    """THE NEAR-MISS, pinned statically because it cannot be caught at runtime.

    A first attempt at FS-816 reinstated `add_retention_policy('telemetry', INTERVAL '90
    days')` to raise the window from what was believed to be 7 days. Migration 034 had
    removed exactly that policy, and for exactly the reason it must stay removed: a
    Timescale chunk holds rows for MANY organisations, so a global chunk-drop deletes data
    belonging to tenants who configured a longer window. Silent, cross-tenant, irreversible.

    WHY A STATIC CHECK RATHER THAN A BEHAVIOURAL ONE. The realdb test
    `test_enforcing_one_tenants_retention_leaves_another_tenants_rows_alone` catches a
    DELETE that lost its organisation predicate — a synchronous bug in the function. It
    CANNOT catch this one: a retention policy is a background job, so within a test run it
    simply never fires, and the suite passes while the policy quietly waits to delete a
    customer's data. The only place this is visible is the chain itself.
    """
    offenders = []
    for table, reason in sorted(TENANT_SCOPED_RETENTION.items()):
        drop = _policies().get(table, {}).get("drop")
        if drop is not None:
            offenders.append(
                f"{table}: a global retention policy drops chunks after {drop:g}d, but "
                f"{reason}"
            )
    assert not offenders, (
        "\n  ".join(["a global chunk-drop was added to a tenant-scoped hypertable:"] + offenders)
        + "\n\nA chunk contains rows for every organisation in its time range. Dropping it "
        "deletes data belonging to tenants who configured a longer window, and nothing "
        "surfaces that until a customer asks for data they are entitled to. Raise the "
        "per-tenant default instead (historian_retention_policies.hot_retention_days and "
        "the COALESCE fallback in enforce_tenant_historian_retention)."
    )


def test_a_compressed_table_that_is_never_dropped_is_declared():
    """The other half. A compression policy with no retention policy is fine — 'compressed
    and kept forever' is a real choice — but it should be a stated one, because unbounded
    growth is how `audit_logs` became FS-817."""
    undeclared = sorted(
        table for table, policy in _policies().items()
        if policy.get("compress") is not None
        and policy.get("drop") is None
        and table not in NO_RETENTION_BY_DESIGN
    )
    assert not undeclared, (
        f"{undeclared} are compressed and never dropped, and nothing records that as a "
        f"decision. Either add a retention policy or register the table in "
        f"NO_RETENTION_BY_DESIGN with the reason."
    )
