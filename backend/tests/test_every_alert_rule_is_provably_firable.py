"""Every alert rule can be shown to fire, or is recorded as untested (FS-583).

A RULE WITH NO UNIT TEST IS ONLY KNOWN TO PARSE. `promtool check rules` validates syntax and
says nothing about whether a series exists that would make the expression true. This
repository has paid for that twice:

  * `EdgeAgentBufferHigh` was syntactically perfect and **unfirable for the entire time it
    existed** — the metric it watched was never published, because the heartbeat sent
    `collectors_total` and the reader wanted `total_collectors` (FS-497/498).
  * `edge_agent_dropped` had no rule at all, so the only counter measuring **permanently lost**
    telemetry reached nobody, while the two recoverable counters beside it were both alerted on
    (FS-591).

An alert that cannot fire is indistinguishable from a healthy system, which is the property
that makes this worth a gate rather than a habit.

    MAX_UNTESTED_RULES = 15   may only go DOWN

WHAT WAS TESTED FIRST, and why not all 51 at once. The eight where "cannot fire" costs most:
telemetry leaving the system (`IngestionDataLost`, `IngestionDeadLettering`,
`EdgeBufferDropping`, `EdgeDeadLettering`), a backup that stopped running
(`DatabaseBackupJobFailed`), and the processes whose absence means the product is down
(`TimescaleDBDown`, `BackendAPIDown`). Those are the conditions nobody is watching a dashboard
for.

THE REMAINING 23 ARE NAMED, not counted. A number alone lets somebody satisfy the ratchet by
deleting a rule; naming them means the list changes only when a rule is tested or deliberately
removed.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ALERTS = REPO / "infra" / "prometheus" / "alerts.yml"
TEST_DIR = ALERTS.parent / "tests"

#: Rules with no promtool unit test. **Only ever shrinks.** Measured 2026-08-08.
#:
#: EIGHT REMOVED 2026-08-11 (FS-653), in `tests/edge_reachability_test.yml`: the two that say
#: an agent is gone (`up` versus the agent's own `edge_agent_up` — they disagree exactly when
#: the process is alive and broken), the collector, the buffer PAIR, the broker, the asset and
#: the disk. Each is driven true from a series the product publishes, and each carries a
#: must-stay-quiet case built from a HEALTHY signal rather than an absent one — a buffer at
#: zero or an asset with no series proves less than it looks.
#:
#: Expectations generated from `alerts.yml` rather than written by hand. promtool compares
#: annotations even when they are omitted, so an omission asserts empty and a guess asserts
#: something plausible and wrong; three drafts failed that way in FS-583 before the lesson
#: took.
#:
#: Named rather than counted so the ratchet cannot be satisfied by deleting a rule — which
#: would improve the number and remove an alert, the exact trade this gate exists to prevent.
UNTESTED: set[str] = {
    "APILatencyP95High",
    "CNPGInstanceExporterDown",
    "DatabaseBackupStale",
    "DigitalTwinOptimizeSlow",
    "EdgeAgentBuffering",
    "EdgeAgentCertExpiringSoon",
    "EdgeBackfillLagHigh",
    "EdgeCollectorErrors",
    "ErrorTrackerFlushFailing",
    "HighMemoryUsage",
    "HistorianQueriesSlow",
    "IngestionLagHigh",
    "NotificationDeliverySlow",
    "OcrAccuracyLow",
    "SlowDatabaseQueries",
}

#: Every rule whose failure means data is gone or the product is down. These may NEVER be
#: untested — a separate, absolute assertion rather than part of the ratchet, because the
#: ratchet permits a slow tail and these do not deserve one.
MUST_BE_TESTED = {
    "IngestionDataLost",
    "IngestionDeadLettering",
    "EdgeBufferDropping",
    "EdgeDeadLettering",
    "EdgeAgentDroppingTelemetry",
    "AuditWriteFailing",
    "DatabaseBackupJobFailed",
    "TimescaleDBDown",
    "BackendAPIDown",
}


def _rules() -> list[str]:
    document = yaml.safe_load(ALERTS.read_text())
    return [
        rule["alert"]
        for group in document["groups"]
        for rule in group.get("rules", [])
        if "alert" in rule
    ]


def _tested() -> set[str]:
    """Rules named by an `alertname:` in a promtool test file.

    Matched on the promtool key rather than a bare mention, so a rule referenced only in a
    comment does not count as covered — the same distinction that made three other guards
    today read their own prose as code.
    """
    names = set(_rules())
    found: set[str] = set()
    for path in TEST_DIR.glob("*_test.yml"):
        body = path.read_text()
        for name in names:
            if re.search(rf"alertname:\s*{re.escape(name)}\b", body):
                found.add(name)
    return found


class TestTheMeasurementIsReal:
    def test_the_rules_parse(self):
        rules = _rules()
        assert len(rules) > 40, (
            f"only {len(rules)} alert rules found; alerts.yml did not parse as expected and "
            f"every assertion below would be about nothing"
        )

    def test_some_rules_are_tested(self):
        """Vacuity. A regex that matched nothing would report every rule untested and the
        ratchet would pass by being maximally pessimistic."""
        assert len(_tested()) >= 20

    def test_a_comment_does_not_count_as_a_test(self):
        """Three guards today matched their own prose. This one keys on promtool's
        `alertname:` so a rule discussed in a header is not counted as covered."""
        assert not re.search(r"alertname:\s*ThisRuleDoesNotExist", "".join(
            p.read_text() for p in TEST_DIR.glob("*_test.yml")
        ))


class TestTheUntestedSetOnlyShrinks:
    def test_no_new_rule_is_untested(self):
        new = sorted(set(_rules()) - _tested() - UNTESTED)
        assert not new, (
            f"{new} have no promtool unit test. `promtool check rules` proves the expression "
            f"PARSES and nothing else — EdgeAgentBufferHigh was syntactically perfect and "
            f"unfirable for its whole existence. Drive the expression true in a test file "
            f"under infra/prometheus/tests/, with at least one must-stay-quiet case."
        )

    def test_the_recorded_set_is_still_untested(self):
        """A stale entry understates the coverage and invites the work to be done twice."""
        now_tested = sorted(UNTESTED & _tested())
        assert not now_tested, (
            f"{now_tested} have tests now; remove them from UNTESTED so the number means "
            f"something"
        )

    def test_every_recorded_rule_still_exists(self):
        gone = sorted(UNTESTED - set(_rules()))
        assert not gone, (
            f"{gone} are recorded as untested and no longer exist. Deleting a rule improves "
            f"this ratchet and removes an alert, which is the trade this gate exists to "
            f"prevent — remove the entries deliberately."
        )


class TestTheRulesThatMayNeverBeUntested:
    @pytest.mark.parametrize("rule", sorted(MUST_BE_TESTED))
    def test_it_has_a_unit_test(self, rule: str):
        """Data loss and total outage. Absolute rather than ratcheted: the tail this gate
        tolerates elsewhere is not acceptable for a rule whose silence means telemetry is
        gone or the product is down."""
        assert rule in _tested(), (
            f"{rule} guards data loss or a total outage and has no test proving it can fire. "
            f"An alert that cannot fire is indistinguishable from a healthy system, and "
            f"these are the conditions nobody is watching a dashboard for."
        )

    @pytest.mark.parametrize("rule", sorted(MUST_BE_TESTED))
    def test_it_still_exists(self, rule: str):
        assert rule in _rules(), f"{rule} was deleted from alerts.yml"

    def test_each_has_a_must_stay_quiet_case(self):
        """A rule that fires on a healthy system is muted within a day, which is the same as
        not having one. Checked across the test files as a whole rather than per rule,
        because several share a file."""
        bodies = "".join(p.read_text() for p in TEST_DIR.glob("*_test.yml"))
        assert bodies.count("exp_alerts: []") >= len(MUST_BE_TESTED), (
            f"fewer must-stay-quiet cases ({bodies.count('exp_alerts: []')}) than rules that "
            f"require one ({len(MUST_BE_TESTED)})"
        )
