"""The heartbeat reports the numbers the agent actually has (FS-497).

THE DEFECT. `heartbeat.build_payload` reads five keys — `buffer_pending`, `dead_lettered`,
`dropped`, `active_collectors`, `total_collectors` (`heartbeat.py:48-52`). `EdgeAgent
._health_snapshot()` returned `collectors_total` and `collectors_active` — different spellings
— and no buffer keys at all. Every read has a `, 0` default, so **every heartbeat this agent
has ever sent reported five zeros.**

It is not cosmetic. `backend/app/services/edge_fleet.py:69` sets the `edge_agent_buffer_pending`
gauge from that field, and `infra/prometheus/alerts.yml:241` alerts on it exceeding 5000. The
alert could not fire. A fleet of agents backing up on disk would have looked idle.

WHY NO TEST SAW IT. `tests/test_heartbeat.py:9-16` defines its own `health()` returning a dict
with the **correct** key names. It is a good test of the reporter and it can say nothing about
the producer, because the two were never connected in a test. The bug lived precisely in the
join: both halves were individually right and disagreed about the contract between them.

So this file asserts the join. It builds a real `EdgeAgent`, takes its real `_health_snapshot`,
and runs it through the real `HeartbeatReporter` — no hand-written dict anywhere.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opsgrid_agent.heartbeat import HeartbeatReporter  # noqa: E402

from tests.test_edge_agent_integration import new_agent  # noqa: E402

#: Every field the reporter reads out of the health snapshot.
REPORTED = ("buffer_pending", "dead_lettered", "dropped", "active_collectors", "total_collectors")


def _payload_from(agent) -> dict:
    """The real snapshot through the real reporter."""
    reporter = HeartbeatReporter(
        "https://cloud", "1.2.3", agent._health_snapshot, post_fn=lambda *a: (200, {})
    )
    return reporter.build_payload()


class TheHeartbeatCarriesTheAgentsOwnNumbers(unittest.TestCase):
    def test_the_snapshot_supplies_every_field_the_reporter_reads(self):
        """The assertion the two separate tests could not make between them."""
        agent = new_agent()
        snapshot = agent._health_snapshot()

        missing = [key for key in REPORTED if key not in snapshot]
        self.assertEqual(
            missing,
            [],
            f"`_health_snapshot()` does not supply {missing}, so `build_payload` falls back "
            f"to its `, 0` defaults and the heartbeat reports zeros for them. This is the "
            f"FS-497 shape: two halves that are each correct and disagree about the names "
            f"between them.",
        )

    def test_collector_counts_survive_the_join(self):
        agent = new_agent()
        agent.coordinator.get_status = lambda: {
            "total_collectors": 4,
            "active_collectors": 3,
        }

        payload = _payload_from(agent)

        self.assertEqual(payload["total_collectors"], 4)
        self.assertEqual(payload["active_collectors"], 3)

    def test_buffer_depth_survives_the_join(self):
        """The field the alert depends on.

        `_stats_reporter` caches these; the snapshot is sync and cannot await the buffer.
        """
        agent = new_agent()
        agent._buffer_snapshot = {"pending": 7321, "dead_lettered": 12, "dropped": 4}

        payload = _payload_from(agent)

        self.assertEqual(
            payload["buffer_pending"],
            7321,
            "a backed-up buffer still reports 0, so `EdgeAgentBufferHigh` cannot fire",
        )
        self.assertEqual(payload["dead_lettered"], 12)
        self.assertEqual(payload["dropped"], 4)

    def test_zero_before_the_first_stats_pass_is_honest(self):
        """The other direction. Nothing has been measured yet, so 0 is the true answer —
        and it must not be confused with the defect above, which reported 0 forever."""
        agent = new_agent()
        agent._buffer_snapshot = {}

        payload = _payload_from(agent)

        self.assertEqual(payload["buffer_pending"], 0)

    def test_the_old_healthz_spellings_are_still_present(self):
        """`/healthz` consumers may read `collectors_total`/`collectors_active`. Fixing one
        silent break by introducing another is not a fix."""
        agent = new_agent()
        snapshot = agent._health_snapshot()

        self.assertIn("collectors_total", snapshot)
        self.assertIn("collectors_active", snapshot)


if __name__ == "__main__":
    unittest.main()
