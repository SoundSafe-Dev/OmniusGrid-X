"""Clock-driven recurrence and rollout scheduling coverage."""

from __future__ import annotations

from datetime import datetime, time, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.models import AgentRolloutEvent
from app.services.maintenance_windows import (
    evaluate_group_windows,
    evaluate_rollout_groups,
)
from app.services.rollout_orchestrator import RolloutOrchestrator
from tests.test_rollout_orchestrator_unit import (
    FakeCommandClient,
    FakeSession,
    _rollout,
)


UTC = timezone.utc


def _window(
    *,
    site_id=None,
    timezone_name="America/Chicago",
    weekdays=(0, 1, 2, 3, 4, 5, 6),
    start=time(2, 0),
    end=time(4, 0),
    enabled=True,
):
    return SimpleNamespace(
        id=uuid4(),
        site_id=site_id,
        timezone=timezone_name,
        weekdays=list(weekdays),
        local_start_time=start,
        local_end_time=end,
        enabled=enabled,
    )


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _event_types(session):
    return [
        item.event_type
        for item in session.added
        if isinstance(item, AgentRolloutEvent)
    ]


def test_weekday_window_and_week_wrap_next_opening():
    monday = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
    rule = _window(weekdays=(0,))

    open_result = evaluate_group_windows(
        [rule],
        [None],
        at=monday,
    )
    assert open_result.is_open is True
    assert open_result.current_closes_at == datetime(
        2026,
        7,
        20,
        9,
        0,
        tzinfo=UTC,
    )

    closed_result = evaluate_group_windows(
        [rule],
        [None],
        at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
    )
    assert closed_result.is_open is False
    assert closed_result.next_eligible_at == datetime(
        2026,
        7,
        27,
        7,
        0,
        tzinfo=UTC,
    )


def test_overnight_window_uses_start_day_weekday():
    friday_overnight = _window(
        timezone_name="UTC",
        weekdays=(4,),
        start=time(22, 0),
        end=time(2, 0),
    )
    result = evaluate_group_windows(
        [friday_overnight],
        [None],
        at=datetime(2026, 7, 25, 1, 30, tzinfo=UTC),
    )
    assert result.is_open is True
    assert result.current_closes_at == datetime(
        2026,
        7,
        25,
        2,
        0,
        tzinfo=UTC,
    )


def test_site_windows_override_org_windows_and_missing_scope_fails_closed():
    site_id = uuid4()
    other_site_id = uuid4()
    org_window = _window(timezone_name="UTC", start=time(1), end=time(5))
    site_window = _window(
        site_id=site_id,
        timezone_name="UTC",
        start=time(10),
        end=time(12),
    )

    result = evaluate_group_windows(
        [org_window, site_window],
        [site_id],
        at=datetime(2026, 7, 24, 2, 0, tzinfo=UTC),
    )
    assert result.is_open is False
    assert result.next_eligible_at == datetime(
        2026,
        7,
        24,
        10,
        0,
        tzinfo=UTC,
    )

    missing = evaluate_group_windows(
        [site_window],
        [other_site_id],
        at=datetime(2026, 7, 24, 2, 0, tzinfo=UTC),
    )
    assert missing.missing_site_ids == (other_site_id,)
    assert missing.next_eligible_at is None


def test_multi_site_agent_uses_intersection_across_timezones():
    chicago_site = uuid4()
    new_york_site = uuid4()
    windows = [
        _window(
            site_id=chicago_site,
            timezone_name="America/Chicago",
            start=time(2),
            end=time(4),
        ),
        _window(
            site_id=new_york_site,
            timezone_name="America/New_York",
            start=time(3),
            end=time(5),
        ),
    ]
    result = evaluate_rollout_groups(
        windows,
        {"agent:shared": {chicago_site, new_york_site}},
        at=datetime(2026, 7, 24, 7, 30, tzinfo=UTC),
    )
    assert result.eligible_group_keys == ("agent:shared",)
    assert result.groups[0].eligibility.current_closes_at == datetime(
        2026,
        7,
        24,
        9,
        0,
        tzinfo=UTC,
    )


def test_spring_forward_nonexistent_boundary_advances_to_first_valid_time():
    rule = _window(
        weekdays=(6,),
        start=time(2, 30),
        end=time(4),
    )
    result = evaluate_group_windows(
        [rule],
        [None],
        at=datetime(2026, 3, 8, 8, 15, tzinfo=UTC),
    )
    assert result.is_open is True
    occurrence = result.occurrences[0]
    assert occurrence.start_at == datetime(2026, 3, 8, 8, 0, tzinfo=UTC)
    assert occurrence.end_at == datetime(2026, 3, 8, 9, 0, tzinfo=UTC)


def test_fall_back_ambiguous_window_keeps_both_repeated_hours():
    rule = _window(
        weekdays=(6,),
        start=time(1),
        end=time(2),
    )
    result = evaluate_group_windows(
        [rule],
        [None],
        at=datetime(2026, 11, 1, 7, 30, tzinfo=UTC),
    )
    assert result.is_open is True
    occurrence = result.occurrences[0]
    assert occurrence.start_at == datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    assert occurrence.end_at == datetime(2026, 11, 1, 8, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_scheduled_rollout_pauses_and_resumes_across_nights(monkeypatch):
    session = FakeSession()
    commands = FakeCommandClient()
    clock = MutableClock(datetime(2026, 7, 24, 6, 0, tzinfo=UTC))
    orchestrator = RolloutOrchestrator(
        command_client=commands,
        clock=clock,
    )
    rollout = _rollout(waves=(0, 1))
    rollout.enforce_maintenance_windows = True
    rollout.scheduled_start_at = datetime(2026, 7, 24, 6, 0, tzinfo=UTC)
    site_id = uuid4()
    for target in rollout.targets:
        target.site_id = site_id
        target.agent_id = f"agent-{target.wave_index}"
    windows = [
        _window(
            site_id=site_id,
            timezone_name="America/Chicago",
            start=time(2),
            end=time(4),
        )
    ]

    async def evaluate(_session, _rollout, groups, *, at):
        return evaluate_rollout_groups(windows, groups, at=at)

    async def healthy(_session, _target, _release, _strategy):
        return True

    monkeypatch.setattr(orchestrator, "_window_eligibility", evaluate)
    monkeypatch.setattr(orchestrator, "_target_healthy", healthy)

    await orchestrator._process_rollout(session, rollout)
    assert rollout.status == "paused"
    assert rollout.pause_reason == "maintenance_window"
    assert commands.submissions == []

    clock.value = datetime(2026, 7, 24, 7, 0, tzinfo=UTC)
    await orchestrator._process_rollout(session, rollout)
    assert rollout.status == "running"
    assert len(commands.submissions) == 1
    assert rollout.targets[0].status == "updating"

    commands.statuses["cmd-1"] = {"status": "completed", "result": {}}
    clock.value = datetime(2026, 7, 24, 9, 1, tzinfo=UTC)
    await orchestrator._process_rollout(session, rollout)
    assert rollout.targets[0].status == "success"
    assert rollout.targets[1].status == "pending"
    assert rollout.status == "paused"
    assert len(commands.submissions) == 1

    clock.value = datetime(2026, 7, 25, 7, 0, tzinfo=UTC)
    await orchestrator._process_rollout(session, rollout)
    assert rollout.status == "running"
    assert rollout.targets[1].status == "updating"
    assert len(commands.submissions) == 2
    assert _event_types(session).count("maintenance_window_paused") == 2
    assert _event_types(session).count("maintenance_window_resumed") == 2


@pytest.mark.asyncio
async def test_schedule_not_before_and_manual_pause_never_auto_resumes():
    session = FakeSession()
    commands = FakeCommandClient()
    clock = MutableClock(datetime(2026, 7, 24, 10, 0, tzinfo=UTC))
    orchestrator = RolloutOrchestrator(command_client=commands, clock=clock)
    rollout = _rollout(waves=(0,))
    rollout.scheduled_start_at = datetime(2026, 7, 24, 11, 0, tzinfo=UTC)

    await orchestrator._process_rollout(session, rollout)
    assert rollout.status == "pending"
    assert commands.submissions == []

    clock.value = datetime(2026, 7, 24, 11, 0, tzinfo=UTC)
    await orchestrator._process_rollout(session, rollout)
    assert rollout.status == "running"
    assert len(commands.submissions) == 1

    manually_paused = _rollout(waves=(0,))
    manually_paused.status = "paused"
    manually_paused.pause_reason = "manual"
    manually_paused.enforce_maintenance_windows = True
    await orchestrator._process_rollout(session, manually_paused)
    assert manually_paused.status == "paused"
    assert manually_paused.pause_reason == "manual"
    assert len(commands.submissions) == 1


@pytest.mark.asyncio
async def test_rollbacks_dispatch_per_site_without_requiring_window_overlap(
    monkeypatch,
):
    session = FakeSession()
    commands = FakeCommandClient()
    clock = MutableClock(datetime(2026, 7, 24, 1, 30, tzinfo=UTC))
    orchestrator = RolloutOrchestrator(command_client=commands, clock=clock)
    rollout = _rollout(
        waves=(0, 0),
        strategy={"failure_threshold": 1},
    )
    rollout.status = "running"
    rollout.enforce_maintenance_windows = True
    first_site = uuid4()
    second_site = uuid4()
    for index, target in enumerate(rollout.targets):
        target.status = "failed"
        target.agent_id = f"agent-{index}"
        target.site_id = first_site if index == 0 else second_site

    windows = [
        _window(
            site_id=first_site,
            timezone_name="UTC",
            start=time(1),
            end=time(2),
        ),
        _window(
            site_id=second_site,
            timezone_name="UTC",
            start=time(3),
            end=time(4),
        ),
    ]
    rollback_release = rollout.release

    async def evaluate(_session, _rollout, groups, *, at):
        return evaluate_rollout_groups(windows, groups, at=at)

    async def rollback(_session, _rollout):
        return rollback_release

    monkeypatch.setattr(orchestrator, "_window_eligibility", evaluate)
    monkeypatch.setattr(orchestrator, "_rollback_release", rollback)

    await orchestrator._process_rollout(session, rollout)
    assert rollout.status == "paused"
    assert rollout.pause_reason == "maintenance_window"
    assert rollout.targets[0].status == "rolled_back"
    assert rollout.targets[1].status == "failed"
    assert len(commands.submissions) == 1

    clock.value = datetime(2026, 7, 24, 3, 30, tzinfo=UTC)
    await orchestrator._process_rollout(session, rollout)
    assert rollout.status == "rolled_back"
    assert [target.status for target in rollout.targets] == [
        "rolled_back",
        "rolled_back",
    ]
    assert len(commands.submissions) == 2
