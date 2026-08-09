"""One reconnect policy, tunable per site, validated at construction (FS-473).

FS-472 gave five collectors a backoff and a breaker by copying the same four constants into
each. That left **sixteen occurrences of the same numbers across eight files**, and one of
those files carried a `TODO(tune)` saying they were a first-pass guess pending production
telemetry.

A guess in one place is a guess. A guess in eight places is a guess nobody can revise: the
person who eventually has the telemetry has to find all eight, and the ones they miss keep
the old behaviour while looking tuned. Worse, the five new copies were **less capable than
the three they were copied from** — `modbus`, `opcua` and `mqtt` accept an injected backoff
or breaker, and the copies accepted nothing.

`ReconnectPolicy` owns the numbers now. They have not changed; they are still the same guess.
What changed is that there is one place to change them, a `reconnect:` block in collector
config to override them per site, and injection everywhere for the coordinator.

WHAT THE VALIDATION IS FOR, since a policy object could have been a dict:

* **an unknown key is an error.** A typo in YAML that silently keeps the default is the shape
  of every config defect in this repository — the operator believes they tuned it and nothing
  says otherwise;
* **the pair has to agree.** A backoff whose cap exceeds the breaker's cooldown cap means the
  loop is already waiting longer than the cooldown, so opening the breaker changes nothing.
  The instrument is present and inert, which this repository has a rule about.
"""

from __future__ import annotations

import unittest

from opsgrid_agent.resilience import CircuitBreaker, ExponentialBackoff, ReconnectPolicy


class TestTheDefaultsAreTheOnesThatShipped(unittest.TestCase):
    """The refactor must not have changed behaviour. These are the values the eight
    collectors carried inline before the policy existed."""

    def test_the_backoff_defaults(self):
        policy = ReconnectPolicy()
        self.assertEqual(policy.initial_delay, 1.0)
        self.assertEqual(policy.max_delay, 60.0)
        self.assertEqual(policy.multiplier, 2.0)

    def test_the_breaker_defaults(self):
        policy = ReconnectPolicy()
        self.assertEqual(policy.failure_threshold, 5)
        self.assertEqual(policy.initial_cooldown, 30.0)
        self.assertEqual(policy.cooldown_cap, 300.0)
        self.assertEqual(policy.cooldown_multiplier, 2.0)

    def test_it_builds_a_matched_pair(self):
        backoff, breaker = ReconnectPolicy().instruments("modbus:asset-1")
        self.assertIsInstance(backoff, ExponentialBackoff)
        self.assertIsInstance(breaker, CircuitBreaker)
        self.assertEqual(breaker.name, "modbus:asset-1")

    def test_the_curve_is_the_one_that_was_measured(self):
        """FS-472 measured 1, 2, 4, 8, 16 on a dead device. If the defaults move, that
        measurement stops describing the product."""
        backoff, _ = ReconnectPolicy().instruments("x")
        self.assertEqual(
            [backoff.next_delay() for _ in range(5)], [1.0, 2.0, 4.0, 8.0, 16.0]
        )


class TestItCanBeTunedPerSite(unittest.TestCase):
    def test_a_config_block_overrides(self):
        policy = ReconnectPolicy.from_config(
            {"reconnect": {"initial_delay": 5.0, "max_delay": 120.0, "cooldown_cap": 600.0}}
        )
        self.assertEqual(policy.initial_delay, 5.0)
        self.assertEqual(policy.max_delay, 120.0)

    def test_a_partial_block_keeps_the_other_defaults(self):
        policy = ReconnectPolicy.from_config({"reconnect": {"failure_threshold": 3}})
        self.assertEqual(policy.failure_threshold, 3)
        self.assertEqual(policy.max_delay, 60.0, "an unmentioned key must keep its default")

    def test_no_block_and_no_config_both_give_defaults(self):
        for config in ({}, None, {"reconnect": None}, {"other": "keys"}):
            self.assertEqual(ReconnectPolicy.from_config(config).max_delay, 60.0)

    def test_both_entry_points_agree(self):
        """The kwarg collectors and the config-dict collectors reach the same validation,
        because an operator writing YAML cannot see which kind they are configuring."""
        settings = {"max_delay": 45.0}
        self.assertEqual(
            ReconnectPolicy.from_settings(settings).max_delay,
            ReconnectPolicy.from_config({"reconnect": settings}).max_delay,
        )


class TestItRefusesConfigurationThatWouldNotWork(unittest.TestCase):
    def test_an_unknown_key_is_an_error(self):
        with self.assertRaises(ValueError) as exc:
            ReconnectPolicy.from_config({"reconnect": {"maxdelay": 10}})
        self.assertIn("maxdelay", str(exc.exception))
        self.assertIn("known keys", str(exc.exception), "the error must say what IS valid")

    def test_a_non_mapping_is_an_error(self):
        with self.assertRaises(ValueError):
            ReconnectPolicy.from_config({"reconnect": [1, 2, 3]})

    def test_a_backoff_that_outlasts_the_cooldown_is_refused(self):
        """The instrument-present-and-inert case. With max_delay above cooldown_cap the
        loop already waits longer than the breaker's cooldown, so opening it changes
        nothing and the breaker is decoration."""
        with self.assertRaises(ValueError) as exc:
            ReconnectPolicy(max_delay=600.0, cooldown_cap=300.0)
        self.assertIn("never slow anything down", str(exc.exception))

    def test_equal_is_allowed(self):
        """The boundary. Equal is coherent — the breaker still bounds the steady state."""
        ReconnectPolicy(max_delay=300.0, cooldown_cap=300.0)

    def test_the_primitives_still_validate_their_own_ranges(self):
        """The policy does not duplicate `ExponentialBackoff`'s and `CircuitBreaker`'s own
        checks; it must not swallow them either."""
        with self.assertRaises(ValueError):
            ReconnectPolicy(initial_delay=0).instruments("x")
        with self.assertRaises(ValueError):
            ReconnectPolicy(failure_threshold=0).instruments("x")


class TestTheConstantsLiveInOnePlace(unittest.TestCase):
    def test_no_collector_repeats_them(self):
        """The whole point. Sixteen occurrences across eight files is what this replaced,
        and the way it comes back is one collector 'just overriding one value'."""
        import pathlib

        collectors = pathlib.Path(__file__).resolve().parent.parent / "opsgrid_agent" / "collectors"
        offenders = []
        for path in sorted(collectors.glob("*.py")):
            source = path.read_text()
            for literal in ("failure_threshold=", "cooldown_cap=", "initial_cooldown="):
                if literal in source:
                    offenders.append(f"{path.name}: {literal}")
        self.assertEqual(
            offenders,
            [],
            f"these collectors set reconnect tuning inline rather than through "
            f"ReconnectPolicy: {offenders}. Put the value in the policy, or pass a "
            f"`reconnect:` block in that collector's config.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
