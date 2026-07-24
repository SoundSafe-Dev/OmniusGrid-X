"""Guard: every alert severity has an Alertmanager route.

Alert rules used a 5-level severity scale (critical/high/medium/low/warning) but
alertmanager.yml only routed four of them — the 11 `warning` alerts matched no
route and fell through to the general catch-all receiver instead of their tier.
This asserts every `severity:` value emitted by the rule files has a matching
`match: {severity: ...}` route, so a new severity can't silently go to the
catch-all again. Pure YAML parsing — no promtool/amtool needed.
"""

import re
from pathlib import Path

import yaml

INFRA = Path(__file__).resolve().parents[2] / "infra" / "prometheus"
RULE_FILES = ["alerts.yml", "slo_rules.yml"]


def _severities_in_rules() -> set[str]:
    found: set[str] = set()
    for name in RULE_FILES:
        text = (INFRA / name).read_text()
        found.update(re.findall(r"severity:\s*([a-z]+)", text))
    return found


def _routed_severities() -> set[str]:
    cfg = yaml.safe_load((INFRA / "alertmanager.yml").read_text())
    routed: set[str] = set()
    for route in cfg.get("route", {}).get("routes", []):
        sev = (route.get("match") or {}).get("severity")
        if sev:
            routed.add(sev)
    return routed


def test_every_alert_severity_has_a_route():
    used = _severities_in_rules()
    routed = _routed_severities()
    unrouted = sorted(used - routed)
    assert not unrouted, (
        "alert severities with no Alertmanager route (they fall through to the "
        f"catch-all receiver instead of their tier): {unrouted}. Add a route in "
        "infra/prometheus/alertmanager.yml or change the alerts' severity."
    )
