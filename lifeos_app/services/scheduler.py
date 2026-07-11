# ==============================================================================
# File: lifeos_app/services/scheduler.py
# Description: Deterministic scheduling engine (ENG-SCHED)
# Component: Services / Scheduler
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Greedy earliest-fit scheduler — excludes unmet BLOCKS dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from lifeos_app.models import (
    AppSettings,
    CalendarEvent,
    ExecutionItem,
    ItemDependencyLink,
    ScheduledAllocation,
    SystemEnums,
    TimeAvailabilityBlock,
)

URGENCY_RANK = {
    SystemEnums.UrgencyLevel.IMMEDIATE: 0,
    SystemEnums.UrgencyLevel.HIGH: 1,
    SystemEnums.UrgencyLevel.NORMAL: 2,
    SystemEnums.UrgencyLevel.LOW: 3,
}

_WEEKDAY_FIELDS = (
    "day_monday",
    "day_tuesday",
    "day_wednesday",
    "day_thursday",
    "day_friday",
    "day_saturday",
    "day_sunday",
)


@dataclass
class ScheduleRunResult:
    """Summary of a scheduler pass."""

    ok: bool
    placed: int = 0
    skipped_blocked: int = 0
    skipped_no_slot: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)


def _blocked_item_ids() -> set[int]:
    """Items with unmet BLOCKS dependencies."""
    open_block = ItemDependencyLink.objects.filter(
        from_item=OuterRef("pk"),
        link_type=SystemEnums.DependencyLinkType.BLOCKS,
        to_item__is_deleted=False,
    ).exclude(to_item__status=SystemEnums.ItemStatus.COMPLETED)
    return set(
        ExecutionItem.objects.filter(is_deleted=False)
        .annotate(blocked=Exists(open_block))
        .filter(blocked=True)
        .values_list("pk", flat=True)
    )


def schedulable_candidates():
    """Active items without allocation, excluding dependency-blocked."""
    blocked = _blocked_item_ids()
    return (
        ExecutionItem.objects.filter(is_deleted=False)
        .exclude(status=SystemEnums.ItemStatus.COMPLETED)
        .exclude(status=SystemEnums.ItemStatus.INBOX)
        .filter(allocation__isnull=True)
        .exclude(pk__in=blocked)
        .order_by("priority", "due_at", "title")
    )


def _day_enabled(block: TimeAvailabilityBlock, weekday: int) -> bool:
    return getattr(block, _WEEKDAY_FIELDS[weekday])


def _aware(dt: datetime) -> datetime:
    if timezone.is_aware(dt):
        return dt
    return timezone.make_aware(dt, timezone.get_current_timezone())


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    sorted_iv = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_iv[0]]
    for start, end in sorted_iv[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _subtract_intervals(
    free: list[tuple[datetime, datetime]],
    busy: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    if not busy:
        return free
    result: list[tuple[datetime, datetime]] = []
    busy_m = _merge_intervals(busy)
    for f_start, f_end in free:
        cursor = f_start
        for b_start, b_end in busy_m:
            if b_end <= cursor or b_start >= f_end:
                continue
            if b_start > cursor:
                result.append((cursor, min(b_start, f_end)))
            cursor = max(cursor, b_end)
            if cursor >= f_end:
                break
        if cursor < f_end:
            result.append((cursor, f_end))
    return [(s, e) for s, e in result if e > s]


def _availability_windows(
    start_day: date,
    end_day: date,
    blocks: list[TimeAvailabilityBlock],
) -> list[tuple[datetime, datetime]]:
    windows: list[tuple[datetime, datetime]] = []
    day = start_day
    while day <= end_day:
        for block in blocks:
            if _day_enabled(block, day.weekday()):
                start_dt = _aware(datetime.combine(day, block.start_time))
                end_dt = _aware(datetime.combine(day, block.end_time))
                if end_dt > start_dt:
                    windows.append((start_dt, end_dt))
        day += timedelta(days=1)
    return windows


def _busy_intervals(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    busy: list[tuple[datetime, datetime]] = []
    for ev in CalendarEvent.objects.filter(
        is_blocking=True,
        start_at__lt=end,
        end_at__gt=start,
    ):
        busy.append((ev.start_at, ev.end_at))
    for alloc in ScheduledAllocation.objects.filter(start_at__lt=end, end_at__gt=start):
        busy.append((alloc.start_at, alloc.end_at))
    return busy


def _rank_item(item: ExecutionItem) -> tuple:
    return (
        item.priority,
        URGENCY_RANK.get(item.urgency, 9),
        item.due_at or timezone.make_aware(datetime.max.replace(tzinfo=None)),
        item.title,
    )


@transaction.atomic
def run_scheduler(horizon_days: int = 7) -> ScheduleRunResult:
    """
    Greedy earliest-fit placement into availability minus busy time.

    Excludes items with unmet BLOCKS dependencies from candidates.
    """
    settings = AppSettings.get_solo()
    buffer = timedelta(minutes=settings.scheduler_buffer_minutes or 0)
    now = timezone.now()
    start_day = now.date()
    end_day = start_day + timedelta(days=horizon_days)

    blocks = list(TimeAvailabilityBlock.objects.all())
    if not blocks:
        return ScheduleRunResult(
            ok=False,
            message="No availability blocks configured.",
            warnings=["Add availability in Settings or seed_data."],
        )

    free = _availability_windows(start_day, end_day, blocks)
    free = _subtract_intervals(free, _busy_intervals(now, _aware(datetime.combine(end_day, time.max))))

    blocked_ids = _blocked_item_ids()
    candidates = list(schedulable_candidates())
    skipped_blocked = len(
        ExecutionItem.objects.filter(
            pk__in=blocked_ids,
            is_deleted=False,
            allocation__isnull=True,
        ).exclude(status=SystemEnums.ItemStatus.COMPLETED)
    )

    candidates.sort(key=_rank_item)
    placed = 0
    skipped_no_slot = 0

    for item in candidates:
        duration = timedelta(minutes=max(item.estimated_minutes or 30, 5))
        slot_found = False
        for idx, (slot_start, slot_end) in enumerate(free):
            start = max(slot_start, now)
            end = start + duration + buffer
            if end <= slot_end:
                alloc = ScheduledAllocation.objects.create(
                    execution_item=item,
                    start_at=start,
                    end_at=start + duration,
                    score=float(100 - item.priority * 10),
                    source=SystemEnums.AllocationSource.SOLVER,
                )
                from lifeos_app.services.reminders import rearm_allocation_reminders

                rearm_allocation_reminders(alloc)
                free[idx] = (end + buffer, slot_end)
                placed += 1
                slot_found = True
                break
        if not slot_found:
            skipped_no_slot += 1

    msg = f"Scheduled {placed} item(s)."
    if skipped_blocked:
        msg += f" Skipped {skipped_blocked} blocked by dependencies."
    if skipped_no_slot:
        msg += f" {skipped_no_slot} had no free slot."

    # P5-03: optional Google push after placement (feature-flagged).
    from lifeos_app.services.calendar_push import push_pending_allocations

    push = push_pending_allocations()
    if push.message:
        msg += f" {push.message}"

    return ScheduleRunResult(
        ok=True,
        placed=placed,
        skipped_blocked=skipped_blocked,
        skipped_no_slot=skipped_no_slot,
        message=msg,
    )
