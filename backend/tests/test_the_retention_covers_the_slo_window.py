"""Prometheus keeps data for at least as long as the SLO rules look back (FS-859).

THE DEFECT. `slo_rules.yml` computes `job:slo_availability:ratio28d` as
`avg_over_time(job:slo_availability:ratio5m[28d])`, and the error budget the contract
rests on is derived from it. Prometheus was configured with
`--storage.tsdb.retention.time=15d` in Kubernetes, and with no retention flag at all in
compose — which is the same 15d, by Prometheus's own default.

**So the contractual error budget was computed over 28 days of which 15 existed.**

Prometheus does not error on that, and that is what makes it dangerous. `avg_over_time`
averages the samples present in the window and ignores the absent ones, so the query
returns a confident number derived from roughly half the period it claims to describe. The
omission is not random either: it drops the OLDEST half, so a bad first fortnight
disappears from the month's budget and the figure reads better than reality.

It is the same shape as the finding that opened this sprint — `clamp_min` making
availability read 1.0 during a total outage — one layer further down. Wave 1 fixed the
expression; this is the store underneath it.

WHY A TEST AND NOT JUST A BIGGER NUMBER. The window and the retention live in different
files, in different languages, deployed by different jobs. Widening a window is a one-line
change to a rules file that silently makes retention insufficient, and nothing about the
edit would suggest looking at a Deployment's args. So the requirement is DERIVED from the
rules rather than restated here.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
RULES = [
    REPO / "infra/prometheus/slo_rules.yml",
    REPO / "infra/prometheus/alerts.yml",
]
K8S_PROMETHEUS = REPO / "infrastructure/k8s/monitoring/prometheus.yaml"
COMPOSE = REPO / "docker-compose.yml"

_DURATION = re.compile(r"\[(\d+)([smhdw])\]")
_UNIT_DAYS = {"s": 1 / 86400, "m": 1 / 1440, "h": 1 / 24, "d": 1, "w": 7}


def _to_days(amount: str, unit: str) -> float:
    return int(amount) * _UNIT_DAYS[unit]


def longest_window_days() -> float:
    """The longest lookback any recording rule or alert uses, in days."""
    longest = 0.0
    for path in RULES:
        for amount, unit in _DURATION.findall(path.read_text()):
            longest = max(longest, _to_days(amount, unit))
    return longest


def _retention_days(text: str) -> float | None:
    match = re.search(r"--storage\.tsdb\.retention\.time=(\d+)([smhdw])", text)
    return _to_days(match.group(1), match.group(2)) if match else None


class TestTheWalkSeesSomething:
    def test_the_rules_declare_a_real_window(self):
        """Vacuity. If the regex stops matching, every comparison below passes on zero."""
        window = longest_window_days()
        assert window >= 1, (
            f"the longest rule window parsed as {window} days, which means the duration "
            f"scan is broken rather than the rules being short-lived"
        )

    def test_the_slo_window_is_the_contractual_one(self):
        """The 28-day window is not incidental — it is what the uptime commitment quotes,
        so this pins the two together."""
        assert longest_window_days() >= 28


class TestRetentionCoversIt:
    def test_kubernetes_keeps_data_for_the_whole_window(self):
        retention = _retention_days(K8S_PROMETHEUS.read_text())
        assert retention is not None, (
            "no --storage.tsdb.retention.time on the Kubernetes Prometheus. Absent, "
            "Prometheus defaults to 15 days, and every rule looking back further silently "
            "averages over the samples that happen to exist."
        )
        window = longest_window_days()
        assert retention >= window, (
            f"retention is {retention:g}d and the longest rule window is {window:g}d. "
            f"`avg_over_time` does not fail on a partial window — it averages what is "
            f"there and drops the OLDEST samples, so the error budget is computed from "
            f"less than the period it claims and reads better than reality."
        )

    def test_compose_keeps_data_for_the_whole_window(self):
        """Compose is where the SLO rules are actually exercised by hand, so a shorter
        retention there produces a number that disagrees with production for a reason
        nobody would look for."""
        retention = _retention_days(COMPOSE.read_text())
        assert retention is not None, (
            "the compose Prometheus sets no retention, so it uses the 15-day default "
            "while the rules look back 28"
        )
        assert retention >= longest_window_days()

    def test_there_is_headroom_not_just_equality(self):
        """Exactly 28 days of retention for a 28-day window leaves nothing: a query
        evaluated a moment late, a restart that loses the head block, or a clock skew all
        eat into the contractual window."""
        window = longest_window_days()
        for label, text in (
            ("kubernetes", K8S_PROMETHEUS.read_text()),
            ("compose", COMPOSE.read_text()),
        ):
            retention = _retention_days(text)
            assert retention >= window + 5, (
                f"{label} retention is {retention:g}d for a {window:g}d window — under "
                f"six days of headroom. A late evaluation or a lost head block then "
                f"silently shortens the contractual period."
            )


class TestTheStorageIsSizedForIt:
    def test_the_volume_grew_with_the_retention(self):
        """Retention that the disk cannot hold is not retention: Prometheus evicts the
        oldest blocks when it runs out, which restores the exact defect this fixes while
        the flag still says 35d."""
        text = K8S_PROMETHEUS.read_text()
        match = re.search(r"storage:\s*(\d+)Gi", text)
        assert match, "no PVC size found for Prometheus"
        assert int(match.group(1)) >= 48, (
            f"the Prometheus volume is {match.group(1)}Gi. It held 15 days at 20Gi, so "
            f"35 days needs roughly 47 — and when the disk fills, Prometheus drops the "
            f"oldest blocks and the window silently shortens again."
        )
