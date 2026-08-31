"""The agent hears the cloud's backpressure hint, and ignores nonsense (FS-866).

The cloud can now say how much ingest load it is under, in the heartbeat ack the agent
already polls. This is the agent's half: it records the level, and — critically — every
way the signal can be wrong resolves to "carry on sending".

That asymmetry is the design. A backpressure mechanism that fails toward throttling can
silence a fleet on a typo, an old backend, or a malformed response, and a silenced fleet
loses data the same way a shedding one does, only more quietly and for longer.
"""

import pytest

from opsgrid_agent.heartbeat import HeartbeatReporter


def _reporter():
    return HeartbeatReporter.__new__(HeartbeatReporter)


def _with_state():
    reporter = _reporter()
    reporter.ingest_pressure = "normal"
    return reporter


class TestItHearsTheHint:
    @pytest.mark.parametrize("level", ["normal", "elevated", "critical"])
    def test_every_known_level_is_recorded(self, level):
        reporter = _with_state()
        reporter._observe_ingest_pressure({"ingest_pressure": level})
        assert reporter.ingest_pressure == level

    def test_it_tracks_changes_in_both_directions(self):
        """Recovery matters as much as onset: an agent that hears 'critical' and never
        hears 'normal' again has been permanently throttled by one bad minute."""
        reporter = _with_state()
        reporter._observe_ingest_pressure({"ingest_pressure": "critical"})
        assert reporter.ingest_pressure == "critical"
        reporter._observe_ingest_pressure({"ingest_pressure": "normal"})
        assert reporter.ingest_pressure == "normal"


class TestEveryWrongSignalMeansCarryOn:
    def test_an_old_backend_omitting_the_field_changes_nothing(self):
        """The field is new. A backend that predates it must leave the agent behaving
        exactly as it does today, or deploying this would throttle every agent talking to
        an un-upgraded cluster."""
        reporter = _with_state()
        reporter._observe_ingest_pressure({"ok": True, "server_time": "t"})
        assert reporter.ingest_pressure == "normal"

    def test_an_unrecognised_level_is_ignored(self):
        """A typo upstream must not be able to silence a fleet."""
        reporter = _with_state()
        reporter._observe_ingest_pressure({"ingest_pressure": "SLOW_DOWN"})
        assert reporter.ingest_pressure == "normal"

    def test_a_non_dict_response_is_ignored(self):
        reporter = _with_state()
        reporter._observe_ingest_pressure("not a dict")
        assert reporter.ingest_pressure == "normal"

    def test_a_null_level_is_ignored(self):
        reporter = _with_state()
        reporter._observe_ingest_pressure({"ingest_pressure": None})
        assert reporter.ingest_pressure == "normal"

    def test_an_elevated_agent_is_not_stuck_there_by_a_bad_response(self):
        """The combination that matters: throttled, then a malformed ack. It must not
        cement the throttle — but it must not clear it either, because a malformed
        response is not evidence the cloud recovered."""
        reporter = _with_state()
        reporter._observe_ingest_pressure({"ingest_pressure": "elevated"})
        reporter._observe_ingest_pressure({"ingest_pressure": 12345})
        assert reporter.ingest_pressure == "elevated"
