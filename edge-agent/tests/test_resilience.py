import asyncio
from unittest.mock import Mock

import pytest

from opsgrid_agent.resilience import (
    CircuitBreaker,
    CircuitState,
    ExponentialBackoff,
)


class FakeClock:
    def __init__(self, now: float = 0.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_exponential_backoff_sequence_caps_and_resets():
    backoff = ExponentialBackoff(
        initial=0.5,
        cap=4.0,
        multiplier=2.0,
        random_source=lambda: 1.0,
    )

    assert [backoff.next_delay() for _ in range(6)] == [
        0.5,
        1.0,
        2.0,
        4.0,
        4.0,
        4.0,
    ]
    assert backoff.current_delay == 4.0
    assert backoff.last_base_delay == 4.0

    backoff.reset()

    assert backoff.current_delay == 0.5
    assert backoff.last_base_delay is None
    assert backoff.next_delay() == 0.5


@pytest.mark.parametrize(
    ("fraction", "expected_delay"),
    [(0.0, 5.0), (0.5, 7.5), (1.0, 10.0)],
)
def test_exponential_backoff_applies_equal_jitter(fraction, expected_delay):
    backoff = ExponentialBackoff(
        initial=10.0,
        cap=40.0,
        multiplier=2.0,
        random_source=lambda: fraction,
    )

    assert backoff.next_delay() == expected_delay
    assert backoff.last_base_delay == 10.0
    assert backoff.current_delay == 20.0


def test_fleet_retry_deadlines_are_not_simultaneous():
    fleet_size = 64
    outage_time = 1_000.0
    fractions = [(index + 1) / (fleet_size + 1) for index in range(fleet_size)]
    agents = [
        ExponentialBackoff(
            initial=10.0,
            cap=60.0,
            multiplier=2.0,
            random_source=lambda fraction=fraction: fraction,
        )
        for fraction in fractions
    ]

    retry_deadlines = [outage_time + agent.next_delay() for agent in agents]

    assert len(set(retry_deadlines)) == fleet_size
    assert retry_deadlines == sorted(retry_deadlines)
    assert all(
        outage_time + 5.0 < deadline < outage_time + 10.0
        for deadline in retry_deadlines
    )


@pytest.mark.parametrize("fraction", [-0.01, 1.01])
def test_exponential_backoff_rejects_invalid_random_fraction(fraction):
    backoff = ExponentialBackoff(random_source=lambda: fraction)

    with pytest.raises(ValueError, match="random_source"):
        backoff.next_delay()


@pytest.mark.asyncio
async def test_mqtt_connection_manager_sleeps_for_jittered_delay():
    from opsgrid_agent.collectors.mqtt import MQTTCollector

    collector = object.__new__(MQTTCollector)
    collector.broker_host = "mqtt.example.test"
    collector.broker_port = 8883
    collector.asset_id = "agent-7"
    collector.client = Mock()
    collector._connected = False
    collector._stop_event = asyncio.Event()
    collector._breaker = Mock()
    collector._breaker.allow.return_value = True
    collector._backoff = ExponentialBackoff(
        initial=8.0,
        cap=60.0,
        multiplier=2.0,
        random_source=lambda: 0.25,
    )

    async def fail_connection():
        raise asyncio.TimeoutError

    slept_delays = []

    async def capture_sleep(seconds):
        slept_delays.append(seconds)
        collector._stop_event.set()

    collector._wait_for_connection = fail_connection
    collector._sleep_or_stop = capture_sleep

    await collector.start()

    assert slept_delays == [5.0]
    assert collector._backoff.last_base_delay == 8.0
    assert collector._backoff.current_delay == 16.0
    collector._breaker.record_failure.assert_called_once_with()
    collector.client.loop_start.assert_called_once_with()
    collector.client.loop_stop.assert_called()

    collector._on_connect(collector.client, None, None, 0)

    assert collector._connected is True
    assert collector._backoff.current_delay == 8.0
    assert collector._backoff.last_base_delay is None
    collector._breaker.record_success.assert_called_once_with()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"initial": 0.0}, "initial must be > 0"),
        ({"initial": 2.0, "cap": 1.0}, "cap"),
        ({"multiplier": 1.0}, "multiplier must be > 1"),
    ],
)
def test_exponential_backoff_rejects_invalid_configuration(kwargs, message):
    with pytest.raises(ValueError, match=message):
        ExponentialBackoff(**kwargs)


def test_circuit_breaker_opens_after_threshold_and_blocks_until_cooldown():
    clock = FakeClock(now=100.0)
    breaker = CircuitBreaker(
        failure_threshold=3,
        initial_cooldown=10.0,
        cooldown_cap=60.0,
        cooldown_multiplier=2.0,
        time_source=clock,
    )

    assert breaker.allow() is True
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state == CircuitState.CLOSED
    assert breaker.allow() is True

    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    assert breaker.allow() is False
    assert breaker.time_until_retry() == 10.0

    clock.advance(9.5)

    assert breaker.allow() is False
    assert breaker.time_until_retry() == pytest.approx(0.5)

    clock.advance(0.5)

    assert breaker.allow() is True
    assert breaker.state == CircuitState.HALF_OPEN
    assert breaker.time_until_retry() == 0.0


def test_circuit_breaker_successful_half_open_probe_closes_and_resets():
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=2,
        initial_cooldown=5.0,
        cooldown_cap=20.0,
        cooldown_multiplier=2.0,
        time_source=clock,
    )

    breaker.record_failure()
    breaker.record_failure()
    clock.advance(5.0)

    assert breaker.allow() is True
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_success()

    assert breaker.state == CircuitState.CLOSED
    assert breaker.allow() is True
    assert breaker.time_until_retry() == 0.0

    breaker.record_failure()

    assert breaker.state == CircuitState.CLOSED

    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN


def test_circuit_breaker_failed_half_open_probe_reopens_with_capped_cooldown():
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1,
        initial_cooldown=2.0,
        cooldown_cap=5.0,
        cooldown_multiplier=3.0,
        time_source=clock,
    )

    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    assert breaker.time_until_retry() == 2.0

    clock.advance(2.0)
    assert breaker.allow() is True
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    assert breaker.time_until_retry() == 5.0

    clock.advance(5.0)
    assert breaker.allow() is True
    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    assert breaker.time_until_retry() == 5.0


def test_circuit_breaker_ignores_success_while_open():
    clock = FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=1,
        initial_cooldown=10.0,
        cooldown_cap=30.0,
        cooldown_multiplier=2.0,
        time_source=clock,
    )

    breaker.record_failure()
    breaker.record_success()

    assert breaker.state == CircuitState.OPEN
    assert breaker.allow() is False


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"failure_threshold": 0}, "failure_threshold must be >= 1"),
        ({"initial_cooldown": 0.0}, "initial_cooldown must be > 0"),
        ({"initial_cooldown": 5.0, "cooldown_cap": 4.0}, "cooldown_cap"),
        ({"cooldown_multiplier": 1.0}, "cooldown_multiplier must be > 1"),
    ],
)
def test_circuit_breaker_rejects_invalid_configuration(kwargs, message):
    with pytest.raises(ValueError, match=message):
        CircuitBreaker(**kwargs)
