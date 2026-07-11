# ==============================================================================
# File: lifeos_app/services/calendar_grid.py
# Description: Unified month/week calendar grid (BL-CAL-002 / P3-SURF-CAL)
# Component: Services / Plan
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Merged allocations + external events for the Planner calendar grid."""

from __future__ import annotations

from calendar import Calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from lifeos_app.models import CalendarEvent, ScheduledAllocation, SyncedCalendar
from lifeos_app.services.plan import PlanBlock


VIEW_MONTH = "month"
VIEW_WEEK = "week"
VALID_VIEWS = {VIEW_MONTH, VIEW_WEEK}
_MONDAY_CAL = Calendar(firstweekday=0)


@dataclass
class GridDay:
    """One cell in the month/week grid."""

    day: date
    in_month: bool
    is_today: bool
    blocks: list[PlanBlock] = field(default_factory=list)


@dataclass
class SourceFilter:
    """Toggleable layer in the calendar grid."""

    key: str
    label: str
    color: str
    enabled: bool
    kind: str  # allocations | calendar
    calendar_pk: int | None = None


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = timezone.make_aware(datetime.combine(day, time.max))
    return start, end


def _range_bounds(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """Inclusive calendar days → aware datetime window."""
    start, _ = _day_bounds(start_day)
    _, end = _day_bounds(end_day)
    return start, end


def _allocation_color(alloc: ScheduledAllocation) -> str:
    item = alloc.execution_item
    primary = item.primary_container()
    if primary and primary.domain_id:
        return primary.domain.color
    return "#7080F0"


def plan_blocks_for_range(
    start_day: date,
    end_day: date,
    *,
    show_allocations: bool = True,
    calendar_ids: set[int] | None = None,
) -> list[PlanBlock]:
    """
    Merged allocations + calendar events overlapping [start_day, end_day].

    calendar_ids=None → all display_enabled calendars.
    calendar_ids=set() → no calendar events.
    """
    start, end = _range_bounds(start_day, end_day)
    blocks: list[PlanBlock] = []

    if show_allocations:
        for alloc in (
            ScheduledAllocation.objects.filter(start_at__lt=end, end_at__gt=start)
            .select_related("execution_item")
            .order_by("start_at")
        ):
            item = alloc.execution_item
            blocks.append(
                PlanBlock(
                    kind="allocation",
                    start_at=alloc.start_at,
                    end_at=alloc.end_at,
                    title=item.title,
                    color=_allocation_color(alloc),
                    item_id=item.pk,
                    meta=alloc.get_source_display(),
                )
            )

    event_qs = CalendarEvent.objects.filter(
        is_blocking=True,
        start_at__lt=end,
        end_at__gt=start,
    ).select_related("source_calendar")

    if calendar_ids is None:
        event_qs = event_qs.filter(
            source_calendar__isnull=False,
            source_calendar__display_enabled=True,
        )
    elif calendar_ids:
        event_qs = event_qs.filter(source_calendar_id__in=calendar_ids)
    else:
        event_qs = event_qs.none()

    for ev in event_qs.order_by("start_at"):
        cal_label = ev.source_calendar.summary if ev.source_calendar else "Calendar"
        cal_color = ev.source_calendar.color if ev.source_calendar else "#8294AB"
        blocks.append(
            PlanBlock(
                kind="calendar",
                start_at=max(ev.start_at, start),
                end_at=min(ev.end_at, end),
                title=ev.title,
                color=cal_color,
                event_id=ev.pk,
                meta=cal_label,
                is_all_day=ev.is_all_day,
            )
        )

    blocks.sort(key=lambda b: b.start_at)
    return blocks


def _blocks_by_day(blocks: list[PlanBlock], start_day: date, end_day: date) -> dict[date, list[PlanBlock]]:
    """Bucket blocks onto each local calendar day they overlap."""
    by_day: dict[date, list[PlanBlock]] = {}
    day = start_day
    while day <= end_day:
        day_start, day_end = _day_bounds(day)
        day_blocks: list[PlanBlock] = []
        for block in blocks:
            if block.start_at < day_end and block.end_at > day_start:
                day_blocks.append(
                    PlanBlock(
                        kind=block.kind,
                        start_at=max(block.start_at, day_start),
                        end_at=min(block.end_at, day_end),
                        title=block.title,
                        color=block.color,
                        item_id=block.item_id,
                        event_id=block.event_id,
                        meta=block.meta,
                        is_all_day=block.is_all_day,
                    )
                )
        by_day[day] = day_blocks
        day += timedelta(days=1)
    return by_day


def week_start(day: date) -> date:
    """Monday-start week containing day."""
    return day - timedelta(days=day.weekday())


def month_grid_span(year: int, month: int) -> tuple[date, date]:
    """First/last visible dates for a Monday-start month grid (may spill adjacent months)."""
    weeks = _MONDAY_CAL.monthdatescalendar(year, month)
    return weeks[0][0], weeks[-1][-1]


def build_source_filters(*, show_allocations: bool) -> list[SourceFilter]:
    """Sidebar toggles: allocations + each discovered calendar."""
    filters = [
        SourceFilter(
            key="allocations",
            label="LifeOS allocations",
            color="#7080F0",
            enabled=show_allocations,
            kind="allocations",
        )
    ]
    for cal in SyncedCalendar.objects.select_related("integration").order_by(
        "integration__provider", "-is_primary", "summary"
    ):
        provider = cal.integration.get_provider_display()
        filters.append(
            SourceFilter(
                key=f"cal-{cal.pk}",
                label=f"{cal.summary} ({provider})",
                color=cal.color,
                enabled=cal.display_enabled,
                kind="calendar",
                calendar_pk=cal.pk,
            )
        )
    return filters


def set_calendar_display_enabled(synced_calendar: SyncedCalendar, *, enabled: bool) -> None:
    """Toggle whether a calendar appears on the grid (does not change sync)."""
    synced_calendar.display_enabled = enabled
    synced_calendar.save(update_fields=["display_enabled", "updated_at"])


def calendar_grid_context(
    *,
    view: str = VIEW_MONTH,
    anchor: date | None = None,
    show_allocations: bool = True,
) -> dict:
    """Template context for SURF-CAL month/week grid."""
    if view not in VALID_VIEWS:
        view = VIEW_MONTH
    if anchor is None:
        anchor = timezone.localdate()
    today = timezone.localdate()

    if view == VIEW_WEEK:
        start = week_start(anchor)
        end = start + timedelta(days=6)
        prev_anchor = start - timedelta(days=7)
        next_anchor = start + timedelta(days=7)
        title = f"Week of {start.strftime('%b')} {start.day}, {start.year}"
    else:
        start, end = month_grid_span(anchor.year, anchor.month)
        # Navigate by calendar month of the anchor
        if anchor.month == 1:
            prev_anchor = date(anchor.year - 1, 12, 1)
        else:
            prev_anchor = date(anchor.year, anchor.month - 1, 1)
        if anchor.month == 12:
            next_anchor = date(anchor.year + 1, 1, 1)
        else:
            next_anchor = date(anchor.year, anchor.month + 1, 1)
        title = anchor.strftime("%B %Y")

    enabled_cal_ids = set(
        SyncedCalendar.objects.filter(display_enabled=True).values_list("pk", flat=True)
    )
    blocks = plan_blocks_for_range(
        start,
        end,
        show_allocations=show_allocations,
        calendar_ids=enabled_cal_ids,
    )
    by_day = _blocks_by_day(blocks, start, end)

    weeks: list[list[GridDay]] = []
    if view == VIEW_WEEK:
        weeks = [
            [
                GridDay(
                    day=start + timedelta(days=i),
                    in_month=True,
                    is_today=(start + timedelta(days=i)) == today,
                    blocks=by_day.get(start + timedelta(days=i), []),
                )
                for i in range(7)
            ]
        ]
    else:
        for week_dates in _MONDAY_CAL.monthdatescalendar(anchor.year, anchor.month):
            weeks.append(
                [
                    GridDay(
                        day=d,
                        in_month=d.month == anchor.month,
                        is_today=d == today,
                        blocks=by_day.get(d, []),
                    )
                    for d in week_dates
                ]
            )

    return {
        "surface": "plan",
        "plan_subsurface": "calendar",
        "grid_view": view,
        "grid_anchor": anchor,
        "grid_prev": prev_anchor,
        "grid_next": next_anchor,
        "grid_title": title,
        "grid_weeks": weeks,
        "grid_weekday_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "show_allocations": show_allocations,
        "source_filters": build_source_filters(show_allocations=show_allocations),
        "grid_block_count": len(blocks),
    }
