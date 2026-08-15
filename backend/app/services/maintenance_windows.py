"""Pure recurrence and eligibility logic for rollout maintenance windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Sequence
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.datetime_utils import canonical_timezone_key


UTC = timezone.utc
DEFAULT_HORIZON_DAYS = 15
MAX_PREVIEW_HORIZON_DAYS = 31


class MaintenanceWindowValidationError(ValueError):
    """Raised when a recurrence definition cannot be evaluated safely."""


@dataclass(frozen=True)
class WindowOccurrence:
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class GroupWindowEligibility:
    is_open: bool
    next_eligible_at: datetime | None
    current_closes_at: datetime | None
    missing_site_ids: tuple[UUID | None, ...]
    effective_window_ids: tuple[UUID, ...]
    occurrences: tuple[WindowOccurrence, ...]


@dataclass(frozen=True)
class TargetGroupWindowEligibility:
    group_key: str
    site_ids: tuple[UUID | None, ...]
    eligibility: GroupWindowEligibility


@dataclass(frozen=True)
class RolloutWindowEligibility:
    groups: tuple[TargetGroupWindowEligibility, ...]
    eligible_group_keys: tuple[str, ...]
    next_eligible_at: datetime | None

    @property
    def missing_groups(self) -> tuple[TargetGroupWindowEligibility, ...]:
        return tuple(
            group
            for group in self.groups
            if group.eligibility.missing_site_ids
        )

    @property
    def no_opening_groups(self) -> tuple[TargetGroupWindowEligibility, ...]:
        return tuple(
            group
            for group in self.groups
            if not group.eligibility.missing_site_ids
            and group.eligibility.next_eligible_at is None
        )


def utc_datetime(value: datetime) -> datetime:
    """Require an aware datetime and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise MaintenanceWindowValidationError(
            "Datetime values must include a timezone offset"
        )
    return value.astimezone(UTC)


def validate_timezone_name(value: str) -> str:
    """Validate an IANA timezone and return its canonical lookup key."""

    name = value.strip()
    if not name:
        raise MaintenanceWindowValidationError("Timezone is required")
    # `canonical_timezone_key` rather than a local try/except: this caught
    # `ZoneInfoNotFoundError` only, and `ZoneInfo` raises a plain ValueError for a
    # traversal-shaped key like `../etc/passwd`, which escaped uncaught. Two other modules
    # had the same handler and the same hole, and in both it surfaced as a 500.
    key = canonical_timezone_key(name)
    if key is None:
        raise MaintenanceWindowValidationError(f"Unknown IANA timezone '{name}'")
    return key


def validate_weekdays(values: Iterable[int]) -> list[int]:
    """Return a sorted, unique Monday=0 through Sunday=6 weekday set."""

    weekdays = list(values)
    if not weekdays:
        raise MaintenanceWindowValidationError(
            "At least one weekday is required"
        )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in weekdays):
        raise MaintenanceWindowValidationError(
            "Weekdays must be integers from 0 (Monday) through 6 (Sunday)"
        )
    if any(value < 0 or value > 6 for value in weekdays):
        raise MaintenanceWindowValidationError(
            "Weekdays must be between 0 (Monday) and 6 (Sunday)"
        )
    return sorted(set(weekdays))


def validate_local_times(start: time, end: time) -> tuple[time, time]:
    """Require naive local wall times with a nonzero duration."""

    if start.tzinfo is not None or end.tzinfo is not None:
        raise MaintenanceWindowValidationError(
            "Maintenance-window times must be local wall times without an offset"
        )
    if start == end:
        raise MaintenanceWindowValidationError(
            "Maintenance-window start and end times must differ"
        )
    return start, end


def _valid_utc_candidates(local_value: datetime, zone: ZoneInfo) -> list[datetime]:
    candidates: set[datetime] = set()
    for fold in (0, 1):
        aware = local_value.replace(tzinfo=zone, fold=fold)
        candidate = aware.astimezone(UTC)
        round_trip = candidate.astimezone(zone).replace(tzinfo=None)
        if round_trip == local_value:
            candidates.add(candidate)
    return sorted(candidates)


def _resolve_local_boundary(
    local_value: datetime,
    zone: ZoneInfo,
    *,
    opening: bool,
) -> datetime:
    """Resolve ambiguous/nonexistent local wall time deterministically.

    Fall-back openings use the first occurrence and closings use the second,
    keeping the full repeated wall-clock interval. A spring-forward boundary
    inside the gap advances to the first valid local minute.
    """

    candidates = _valid_utc_candidates(local_value, zone)
    if candidates:
        return candidates[0] if opening else candidates[-1]

    probe = local_value
    for _ in range(26 * 60):
        probe += timedelta(minutes=1)
        candidates = _valid_utc_candidates(probe, zone)
        if candidates:
            return candidates[0] if opening else candidates[-1]
    raise MaintenanceWindowValidationError(
        f"Could not resolve local time {local_value.isoformat()} in {zone.key}"
    )


def _window_occurrences(
    window,
    *,
    at: datetime,
    horizon_days: int,
) -> list[WindowOccurrence]:
    zone = ZoneInfo(validate_timezone_name(str(window.timezone)))
    weekdays = set(validate_weekdays(window.weekdays or []))
    start_time, end_time = validate_local_times(
        window.local_start_time,
        window.local_end_time,
    )
    local_anchor = at.astimezone(zone).date()
    utc_limit = at + timedelta(days=horizon_days)
    occurrences: list[WindowOccurrence] = []

    # Include the previous local day so an overnight window can contain `at`.
    for offset in range(-1, horizon_days + 3):
        start_date = local_anchor + timedelta(days=offset)
        if start_date.weekday() not in weekdays:
            continue
        end_date = (
            start_date
            if end_time > start_time
            else start_date + timedelta(days=1)
        )
        local_start = datetime.combine(start_date, start_time)
        local_end = datetime.combine(end_date, end_time)
        start_at = _resolve_local_boundary(local_start, zone, opening=True)
        end_at = _resolve_local_boundary(local_end, zone, opening=False)
        if end_at <= start_at:
            continue
        if end_at <= at or start_at > utc_limit:
            continue
        occurrences.append(WindowOccurrence(start_at=start_at, end_at=end_at))
    return sorted(occurrences, key=lambda item: (item.start_at, item.end_at))


def _merge_occurrences(
    occurrences: Sequence[WindowOccurrence],
) -> list[WindowOccurrence]:
    merged: list[WindowOccurrence] = []
    for occurrence in sorted(
        occurrences,
        key=lambda item: (item.start_at, item.end_at),
    ):
        if not merged or occurrence.start_at > merged[-1].end_at:
            merged.append(occurrence)
            continue
        previous = merged[-1]
        merged[-1] = WindowOccurrence(
            start_at=previous.start_at,
            end_at=max(previous.end_at, occurrence.end_at),
        )
    return merged


def _intersect_occurrences(
    left: Sequence[WindowOccurrence],
    right: Sequence[WindowOccurrence],
) -> list[WindowOccurrence]:
    intersections: list[WindowOccurrence] = []
    left_index = 0
    right_index = 0
    while left_index < len(left) and right_index < len(right):
        left_item = left[left_index]
        right_item = right[right_index]
        start_at = max(left_item.start_at, right_item.start_at)
        end_at = min(left_item.end_at, right_item.end_at)
        if start_at < end_at:
            intersections.append(
                WindowOccurrence(start_at=start_at, end_at=end_at)
            )
        if left_item.end_at <= right_item.end_at:
            left_index += 1
        else:
            right_index += 1
    return _merge_occurrences(intersections)


def _effective_windows(windows: Sequence, site_id: UUID | None) -> list:
    enabled = [window for window in windows if bool(window.enabled)]
    if site_id is not None:
        site_windows = [
            window
            for window in enabled
            if window.site_id is not None
            and str(window.site_id) == str(site_id)
        ]
        if site_windows:
            return site_windows
    return [window for window in enabled if window.site_id is None]


def evaluate_group_windows(
    windows: Sequence,
    site_ids: Iterable[UUID | None],
    *,
    at: datetime,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> GroupWindowEligibility:
    """Evaluate the shared opening for one process-scoped target group.

    Site-specific enabled windows override organization windows for that site.
    Assets without a site use organization windows. A process mapped across
    sites is open only during the intersection of every applicable scope.
    """

    if horizon_days < 1 or horizon_days > MAX_PREVIEW_HORIZON_DAYS:
        raise MaintenanceWindowValidationError(
            f"horizon_days must be between 1 and {MAX_PREVIEW_HORIZON_DAYS}"
        )
    at = utc_datetime(at)
    unique_sites = sorted(
        set(site_ids) or {None},
        key=lambda value: "" if value is None else str(value),
    )
    missing: list[UUID | None] = []
    effective_ids: set[UUID] = set()
    scope_occurrences: list[list[WindowOccurrence]] = []

    for site_id in unique_sites:
        effective = _effective_windows(windows, site_id)
        if not effective:
            missing.append(site_id)
            continue
        effective_ids.update(window.id for window in effective)
        occurrences: list[WindowOccurrence] = []
        for window in effective:
            occurrences.extend(
                _window_occurrences(
                    window,
                    at=at,
                    horizon_days=horizon_days,
                )
            )
        scope_occurrences.append(_merge_occurrences(occurrences))

    if missing:
        return GroupWindowEligibility(
            is_open=False,
            next_eligible_at=None,
            current_closes_at=None,
            missing_site_ids=tuple(missing),
            effective_window_ids=tuple(sorted(effective_ids, key=str)),
            occurrences=(),
        )

    shared = scope_occurrences[0]
    for occurrences in scope_occurrences[1:]:
        shared = _intersect_occurrences(shared, occurrences)
        if not shared:
            break

    current = next(
        (
            occurrence
            for occurrence in shared
            if occurrence.start_at <= at < occurrence.end_at
        ),
        None,
    )
    if current is not None:
        return GroupWindowEligibility(
            is_open=True,
            next_eligible_at=at,
            current_closes_at=current.end_at,
            missing_site_ids=(),
            effective_window_ids=tuple(sorted(effective_ids, key=str)),
            occurrences=tuple(shared),
        )

    next_occurrence = next(
        (occurrence for occurrence in shared if occurrence.start_at > at),
        None,
    )
    return GroupWindowEligibility(
        is_open=False,
        next_eligible_at=(
            next_occurrence.start_at if next_occurrence is not None else None
        ),
        current_closes_at=None,
        missing_site_ids=(),
        effective_window_ids=tuple(sorted(effective_ids, key=str)),
        occurrences=tuple(shared),
    )


def evaluate_rollout_groups(
    windows: Sequence,
    groups: dict[str, Iterable[UUID | None]],
    *,
    at: datetime,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> RolloutWindowEligibility:
    """Evaluate several independently dispatchable process groups."""

    at = utc_datetime(at)
    results: list[TargetGroupWindowEligibility] = []
    for group_key in sorted(groups):
        site_ids = tuple(
            sorted(
                set(groups[group_key]) or {None},
                key=lambda value: "" if value is None else str(value),
            )
        )
        results.append(
            TargetGroupWindowEligibility(
                group_key=group_key,
                site_ids=site_ids,
                eligibility=evaluate_group_windows(
                    windows,
                    site_ids,
                    at=at,
                    horizon_days=horizon_days,
                ),
            )
        )
    eligible_keys = tuple(
        group.group_key
        for group in results
        if group.eligibility.is_open
    )
    next_candidates = [
        group.eligibility.next_eligible_at
        for group in results
        if group.eligibility.next_eligible_at is not None
    ]
    return RolloutWindowEligibility(
        groups=tuple(results),
        eligible_group_keys=eligible_keys,
        next_eligible_at=min(next_candidates) if next_candidates else None,
    )


def effective_scope_label(site_id: UUID | None) -> str:
    return str(site_id) if site_id is not None else "organization"


def local_date_for_weekday(
    anchor: date,
    weekday: int,
) -> date:
    """Small public helper used by clock-driven recurrence tests."""

    return anchor + timedelta(days=(weekday - anchor.weekday()) % 7)
