"""Alertmanager refused to start on its own config, and nothing noticed (FS-787/788).

`infra/prometheus/alertmanager.yml` shipped secrets as shell-style placeholders:

    receivers:
      - name: 'default'
        slack_configs:
          - api_url: '${SLACK_WEBHOOK_URL}'

Alertmanager does not expand environment variables. That much was known — the k8s config
says so in its own header and uses `*_file` correctly. What nobody checked is what the
unexpanded value actually does, which is worse than being wrong:

    $ amtool check-config infra/prometheus/alertmanager.yml
    FAILED: unsupported scheme "" for URL

`${SLACK_WEBHOOK_URL}` is not a URL, so the configuration is INVALID and Alertmanager
exits rather than starting. The compose Alertmanager has therefore never run. Prometheus
has been posting alerts to `alertmanager:9093` (prometheus.yml:8-12), a container in a
restart loop, for the whole life of the file — so the local stack has had rules, a
dashboard, and no notification path whatsoever. The same shape as FS-516 one file over:
configured, verified by four gates, and never once working.

WHY EVERY EXISTING GATE MISSED IT. `test_alert_routing_coverage` parses the YAML and
checks that each severity has a route — a question that is perfectly answerable about a
config Alertmanager will not load. Parsing is not loading. This file asks the second
question in the way that cannot be faked: it validates the semantics Alertmanager
itself enforces, including that no secret-bearing field is a placeholder and that every
inhibit rule is capable of matching something.

`amtool` is not importable, so the checks below reimplement the specific rules that were
broken rather than shelling out. The CI job in quality-gates.yml runs the real
`amtool check-config` alongside these; both exist because the binary is not available in
every environment a developer runs the suite in, and a check that only runs in CI is one
a developer cannot use before pushing.
"""

from __future__ import annotations

import pathlib
import re
from urllib.parse import urlparse

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
CONFIGS = {
    "compose": REPO / "infra" / "prometheus" / "alertmanager.yml",
    "k8s": REPO / "infrastructure" / "k8s" / "monitoring" / "alertmanager-config.yml",
}
#: BOTH rule files, IMPORTED rather than restated — "the files Prometheus loads" is one
#: fact, and test_runbook_links_resolve already owns it. The SLO burn-rate alerts live in
#: slo_rules.yml, and an inhibit rule naming one of them is perfectly valid; a version of
#: this module that read only alerts.yml reported six live rules as dead, which is the
#: same false confidence pointing the other way.
from tests.test_runbook_links_resolve import RULE_FILES  # noqa: E402

#: Fields Alertmanager parses as a URL. A placeholder here is a hard startup failure.
URL_FIELDS = {"api_url", "url", "webhook_url"}
#: Fields carrying a secret in some other form.
SECRET_FIELDS = URL_FIELDS | {"service_key", "routing_key", "auth_password", "auth_token"}


def _receiver_configs(doc: dict):
    """(receiver name, config-kind, config dict) for every notifier in the file."""
    for receiver in doc.get("receivers", []):
        for key, value in receiver.items():
            if not key.endswith("_configs") or not isinstance(value, list):
                continue
            for entry in value:
                if isinstance(entry, dict):
                    yield receiver.get("name", "?"), key, entry


@pytest.mark.parametrize("label", sorted(CONFIGS))
def test_no_secret_field_is_an_unexpanded_placeholder(label):
    doc = yaml.safe_load(CONFIGS[label].read_text())
    offenders = []
    for name, kind, entry in _receiver_configs(doc):
        for field, value in entry.items():
            if field not in SECRET_FIELDS or not isinstance(value, str):
                continue
            if re.search(r"\$\{[^}]+\}|\$[A-Z_]{3,}", value):
                offenders.append(f"{name}.{kind}.{field} = {value!r}")
    assert not offenders, (
        f"{label}: these fields carry a shell-style placeholder:\n  "
        + "\n  ".join(offenders)
        + "\n\nAlertmanager does not expand environment variables, and an unexpanded "
        "value in a URL field is not merely wrong — it is unparseable, so Alertmanager "
        "EXITS and no alert is ever delivered. Use the `*_file` form and mount the "
        "secret (infra/prometheus/alertmanager-secrets/ locally, the "
        "`alertmanager-secrets` Secret in the cluster)."
    )


@pytest.mark.parametrize("label", sorted(CONFIGS))
def test_every_url_field_parses_as_a_url(label):
    doc = yaml.safe_load(CONFIGS[label].read_text())
    bad = []
    for name, kind, entry in _receiver_configs(doc):
        for field, value in entry.items():
            if field not in URL_FIELDS or not isinstance(value, str):
                continue
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                bad.append(f"{name}.{kind}.{field} = {value!r}")
    assert not bad, (
        f"{label}: {bad} are not valid http(s) URLs. This is the exact error "
        f'amtool reports as `unsupported scheme "" for URL`, and it prevents startup.'
    )


@pytest.mark.parametrize("label", sorted(CONFIGS))
def test_secret_file_refs_point_at_a_mounted_path(label):
    """A `*_file` ref to a path nothing mounts fails at startup just as hard."""
    doc = yaml.safe_load(CONFIGS[label].read_text())
    refs = [
        value
        for _n, _k, entry in _receiver_configs(doc)
        for field, value in entry.items()
        if field.endswith("_file") and isinstance(value, str)
    ]
    assert refs, f"{label} declares no *_file secret refs — did they revert to inline?"
    for ref in refs:
        assert ref.startswith("/etc/alertmanager/secrets/"), (
            f"{label}: {ref!r} is outside the mounted secrets directory. Both compose "
            f"and the cluster mount /etc/alertmanager/secrets; a ref anywhere else "
            f"resolves to nothing."
        )
    if label == "compose":
        local = REPO / "infra" / "prometheus" / "alertmanager-secrets"
        for ref in refs:
            name = ref.rsplit("/", 1)[-1]
            assert (local / name).exists(), (
                f"compose references {ref!r} but infra/prometheus/alertmanager-secrets/"
                f"{name} does not exist. The bind mount would create a DIRECTORY at that "
                f"path and Alertmanager would fail to read it — the local stack silently "
                f"loses its notification path again."
            )


def _alert_severities() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in RULE_FILES:
        doc = yaml.safe_load(path.read_text())
        for group in doc.get("groups", []):
            for rule in group.get("rules", []):
                if "alert" in rule:
                    out.setdefault(rule["alert"], set()).add(
                        (rule.get("labels") or {}).get("severity")
                    )
    return out


@pytest.mark.parametrize("label", sorted(CONFIGS))
def test_no_inhibit_rule_is_structurally_incapable_of_matching(label):
    """FS-786. Both original rules required source and target to share an `alertname`
    while differing in `severity`. Every rule in alerts.yml hardcodes one severity and
    all 70 alertnames are distinct, so neither could ever match — and dead inhibition is
    invisible, because it looks exactly like nothing having needed suppression yet."""
    doc = yaml.safe_load(CONFIGS[label].read_text())
    severities = _alert_severities()
    dead = []
    for i, rule in enumerate(doc.get("inhibit_rules", [])):
        src = rule.get("source_match") or {}
        tgt = rule.get("target_match") or {}
        equal = set(rule.get("equal") or [])
        if (
            "alertname" in equal
            and src.get("severity")
            and tgt.get("severity")
            and src["severity"] != tgt["severity"]
        ):
            shared = [a for a, s in severities.items() if len(s) > 1]
            dead.append(
                f"rule {i}: equal={sorted(equal)} requires one alertname to appear at "
                f"both severity={src['severity']!r} and severity={tgt['severity']!r}; "
                f"alertnames carrying more than one severity: {shared or 'NONE'}"
            )
    assert not dead, (
        f"{label}: these inhibit rules can never match:\n  " + "\n  ".join(dead) +
        "\n\nInhibition must key on the subject two alerts share — the volume, the "
        "agent, the instance — not on their name."
    )


@pytest.mark.parametrize("label", sorted(CONFIGS))
def test_every_inhibit_rule_names_alerts_that_exist(label):
    """An inhibit rule naming a deleted or misspelled alert is dead in the same silent
    way, and a matcher regex makes that easy to do."""
    doc = yaml.safe_load(CONFIGS[label].read_text())
    known = set(_alert_severities())
    unknown = []
    for i, rule in enumerate(doc.get("inhibit_rules", [])):
        for side in ("source_matchers", "target_matchers"):
            for matcher in rule.get(side) or []:
                exact = re.fullmatch(r'alertname="([^"]+)"', matcher)
                regex = re.fullmatch(r'alertname=~"([^"]+)"', matcher)
                names = (
                    [exact.group(1)] if exact
                    else regex.group(1).split("|") if regex
                    else []
                )
                for name in names:
                    if name and name not in known:
                        unknown.append(f"rule {i} {side}: {name!r}")
    assert not unknown, (
        f"{label}: inhibit rules reference alerts that do not exist in alerts.yml: "
        f"{unknown}. The rule is dead and looks identical to one that has not yet "
        f"needed to fire."
    )


class TestTheMeasurementIsReal:
    def test_it_found_receiver_configs(self):
        for label, path in CONFIGS.items():
            doc = yaml.safe_load(path.read_text())
            found = list(_receiver_configs(doc))
            assert len(found) >= 4, f"{label}: only {len(found)} notifier configs parsed"

    def test_it_read_both_rule_files(self):
        names = _alert_severities()
        assert "DiskSpaceCritical" in names, "alerts.yml not read"
        assert "SLOErrorBudgetFastBurn" in names, (
            "slo_rules.yml not read — inhibit rules naming the SLO alerts would be "
            "reported as dead when they are live."
        )
        assert len(names) >= 70, f"only {len(names)} alertnames across both files"

    def test_it_found_inhibit_rules(self):
        for label, path in CONFIGS.items():
            doc = yaml.safe_load(path.read_text())
            assert len(doc.get("inhibit_rules") or []) >= 5, (
                f"{label}: fewer inhibit rules than expected — the FS-786 replacements "
                f"may have been reverted to the two dead ones."
            )

    def test_it_would_catch_the_original_shape(self):
        """POSITIVE CONTROL for both defects, run against the configs as they were."""
        original = yaml.safe_load(
            """
            receivers:
              - name: default
                slack_configs:
                  - api_url: '${SLACK_WEBHOOK_URL}'
            inhibit_rules:
              - source_match: {severity: critical}
                target_match: {severity: high}
                equal: ['alertname', 'cluster', 'service']
            """
        )
        name, kind, entry = next(iter(_receiver_configs(original)))
        assert re.search(r"\$\{[^}]+\}", entry["api_url"])
        assert urlparse(entry["api_url"]).scheme not in {"http", "https"}
        rule = original["inhibit_rules"][0]
        assert "alertname" in rule["equal"]
        assert rule["source_match"]["severity"] != rule["target_match"]["severity"]
