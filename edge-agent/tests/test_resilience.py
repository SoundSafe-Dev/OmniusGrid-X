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
    backoff = ExponentialBackoff(initial=0.5, cap=4.0, multiplier=2.0)

    assert [backoff.next_delay() for _ in range(6)] == [
        0.5,
        1.0,
        2.0,
        4.0,
        4.0,
        4.0,
    ]
    assert backoff.current_delay == 4.0

    backoff.reset()

    assert backoff.current_delay == 0.5
    assert backoff.next_delay() == 0.5


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
