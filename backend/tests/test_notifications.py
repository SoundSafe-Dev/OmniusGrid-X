"""Unit tests for the notification matching + dispatch (pure, no DB / no network)."""

from app.services.notifications import NotificationService, severity_rank


def recording_service():
    """A service whose channels record calls instead of doing network I/O."""
    sent = []

    def fake_channel(target, event):
        sent.append((target, event))
        return True, "recorded"

    svc = NotificationService(channels={"webhook": fake_channel, "slack": fake_channel})
    return svc, sent


def test_severity_ranking():
    assert severity_rank("critical") > severity_rank("error") > severity_rank("warning") > severity_rank("info")


def test_matches_severity_threshold():
    svc = NotificationService(channels={})
    rule = {"min_severity": "error", "channel": "webhook"}
    assert svc.matches(rule, {"severity": "critical"}) is True
    assert svc.matches(rule, {"severity": "warning"}) is False


def test_matches_domain_and_asset_filters():
    svc = NotificationService(channels={})
    rule = {"min_severity": "info", "domain": "maintenance", "asset_id": "a1"}
    assert svc.matches(rule, {"severity": "info", "domain": "maintenance", "asset_id": "a1"}) is True
    assert svc.matches(rule, {"severity": "info", "domain": "quality", "asset_id": "a1"}) is False
    assert svc.matches(rule, {"severity": "info", "domain": "maintenance", "asset_id": "a2"}) is False


def test_disabled_rule_never_matches():
    svc = NotificationService(channels={})
    assert svc.matches({"enabled": False, "min_severity": "info"}, {"severity": "critical"}) is False


def test_dispatch_delivers_to_matching_rules_only():
    svc, sent = recording_service()
    event = {"severity": "critical", "title": "Down", "message": "asset offline", "asset_id": "a1"}
    rules = [
        {"id": "s1", "channel": "webhook", "target": "http://x", "min_severity": "warning"},
        {"id": "s2", "channel": "slack", "target": "http://slack", "min_severity": "info", "asset_id": "a1"},
        {"id": "s3", "channel": "webhook", "target": "http://y", "min_severity": "critical", "asset_id": "a2"},  # filtered out
    ]
    results = svc.dispatch_rules(event, rules)
    assert len(results) == 2                                  # s1 + s2 match, s3 filtered
    assert all(r["delivered"] for r in results)
    assert len(sent) == 2
    assert {r["subscription_id"] for r in results} == {"s1", "s2"}


def test_unknown_channel_reports_failure():
    svc = NotificationService(channels={})   # no adapters registered
    results = svc.dispatch_rules(
        {"severity": "critical"},
        [{"id": "s1", "channel": "carrier_pigeon", "target": "-", "min_severity": "info"}],
    )
    assert results[0]["delivered"] is False
    assert "unknown channel" in results[0]["detail"]


def test_channel_exception_is_captured():
    def boom(target, event):
        raise RuntimeError("network down")
    svc = NotificationService(channels={"webhook": boom})
    results = svc.dispatch_rules(
        {"severity": "error"},
        [{"id": "s1", "channel": "webhook", "target": "http://x", "min_severity": "info"}],
    )
    assert results[0]["delivered"] is False
    assert "network down" in results[0]["detail"]
