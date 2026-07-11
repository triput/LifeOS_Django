# ==============================================================================
# File: lifeos_app/services/stability.py
# Description: System Stability Index compute (P4-ENG-STABILITY)
# Component: Services / Stability
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Daily Stability Index from completions + focus vs Settings targets (FR-STAB-*)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Sum
from django.utils import timezone

from lifeos_app.models import (
    AppSettings,
    ExecutionItem,
    FocusSession,
    ScheduledAllocation,
    StabilitySnapshot,
    SystemEnums,
)

STABLE_SCORE_FLOOR = 70
OVERLOAD_FOCUS_RATIO = 1.25


@dataclass(frozen=True)
class StabilityInputs:
    """Raw inputs for one local calendar day."""

    local_date: date
    completions_count: int
    focus_seconds: int
    planned_minutes: int
    completion_target: int
    focus_minutes_target: int


def owner_tz(settings: AppSettings | None = None) -> ZoneInfo:
    """Owner IANA timezone for day boundaries."""
    settings = settings or AppSettings.get_solo()
    try:
        return ZoneInfo(settings.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def local_day_bounds(local_date: date, settings: AppSettings | None = None) -> tuple[datetime, datetime]:
    """UTC-aware [start, end) for a local calendar date."""
    tz = owner_tz(settings)
    start = datetime(local_date.year, local_date.month, local_date.day, tzinfo=tz)
    end = start + timedelta(days=1)
    return start, end


def today_local(settings: AppSettings | None = None) -> date:
    """Owner's current local date."""
    return timezone.now().astimezone(owner_tz(settings)).date()


def count_completions(local_date: date, settings: AppSettings | None = None) -> int:
    """Items marked COMPLETED whose updated_at falls on the local day."""
    start, end = local_day_bounds(local_date, settings)
    return (
        ExecutionItem.objects.filter(
            is_deleted=False,
            status=SystemEnums.ItemStatus.COMPLETED,
            updated_at__gte=start,
            updated_at__lt=end,
        ).count()
    )


def sum_focus_seconds(local_date: date, settings: AppSettings | None = None) -> int:
    """Closed focus duration ending on the local day + open session elapsed if started that day."""
    start, end = local_day_bounds(local_date, settings)
    closed = (
        FocusSession.objects.filter(ended_at__gte=start, ended_at__lt=end).aggregate(
            total=Sum("duration_seconds")
        )["total"]
        or 0
    )
    open_extra = 0
    open_sess = FocusSession.objects.filter(ended_at__isnull=True).first()
    if open_sess and start <= open_sess.started_at < end:
        open_extra = max(0, int((timezone.now() - open_sess.started_at).total_seconds()))
        open_extra += int(open_sess.duration_seconds or 0)
    return int(closed) + int(open_extra)


def sum_planned_minutes(local_date: date, settings: AppSettings | None = None) -> int:
    """Allocation minutes overlapping the local day (busy plan signal)."""
    start, end = local_day_bounds(local_date, settings)
    total = 0
    for alloc in ScheduledAllocation.objects.filter(start_at__lt=end, end_at__gt=start):
        overlap_start = max(alloc.start_at, start)
        overlap_end = min(alloc.end_at, end)
        if overlap_end > overlap_start:
            total += int((overlap_end - overlap_start).total_seconds() // 60)
    return total


def gather_inputs(local_date: date, settings: AppSettings | None = None) -> StabilityInputs:
    """Collect completion/focus/plan inputs for a day."""
    settings = settings or AppSettings.get_solo()
    return StabilityInputs(
        local_date=local_date,
        completions_count=count_completions(local_date, settings),
        focus_seconds=sum_focus_seconds(local_date, settings),
        planned_minutes=sum_planned_minutes(local_date, settings),
        completion_target=max(1, int(settings.daily_completion_target or 1)),
        focus_minutes_target=max(1, int(settings.daily_focus_minutes_target or 1)),
    )


def compute_score_and_band(inputs: StabilityInputs) -> tuple[int, str]:
    """
    Score 0–100 from completion + focus ratios; band STABLE / BEHIND / OVERLOADED.

    Overload = focus well above target (capacity signal, not shame).
    """
    completion_ratio = min(1.0, inputs.completions_count / float(inputs.completion_target))
    focus_minutes = inputs.focus_seconds / 60.0
    # Prefer planned allocation as focus denominator when present; else Settings target.
    focus_denom = float(inputs.planned_minutes or inputs.focus_minutes_target)
    focus_ratio = min(1.5, focus_minutes / focus_denom) if focus_denom else 0.0
    # Cap contribution at 1.0 for score; overload uses raw ratio separately.
    score = int(round(100 * (0.55 * completion_ratio + 0.45 * min(1.0, focus_ratio))))
    score = max(0, min(100, score))

    if focus_ratio >= OVERLOAD_FOCUS_RATIO:
        band = SystemEnums.StabilityBand.OVERLOADED
    elif score >= STABLE_SCORE_FLOOR:
        band = SystemEnums.StabilityBand.STABLE
    else:
        band = SystemEnums.StabilityBand.BEHIND
    return score, band


def compute_streak(local_date: date, settings: AppSettings | None = None) -> int:
    """Consecutive STABLE days ending at local_date (inclusive), capped by window."""
    settings = settings or AppSettings.get_solo()
    window = max(1, int(settings.stability_streak_window_days or 7))
    streak = 0
    cursor = local_date
    for _ in range(window):
        snap = StabilitySnapshot.objects.filter(date=cursor).first()
        if snap is None or snap.band != SystemEnums.StabilityBand.STABLE:
            break
        streak += 1
        cursor = cursor - timedelta(days=1)
    return streak


def compute_stability_for_date(
    local_date: date | None = None,
    *,
    settings: AppSettings | None = None,
) -> StabilitySnapshot:
    """Compute and upsert StabilitySnapshot for a local date."""
    settings = settings or AppSettings.get_solo()
    local_date = local_date or today_local(settings)
    inputs = gather_inputs(local_date, settings)
    score, band = compute_score_and_band(inputs)
    snap, _ = StabilitySnapshot.objects.update_or_create(
        date=local_date,
        defaults={
            "completions_count": inputs.completions_count,
            "focus_seconds": inputs.focus_seconds,
            "planned_minutes": inputs.planned_minutes or inputs.focus_minutes_target,
            "index_score": score,
            "band": band,
            "streak_days": 0,  # filled after save so today counts if STABLE
        },
    )
    # Streak includes today only after band is written
    snap.streak_days = compute_streak(local_date, settings)
    snap.save(update_fields=["streak_days"])
    return snap


def ensure_today_stability(*, settings: AppSettings | None = None) -> StabilitySnapshot:
    """Recompute today's snapshot (safe to call on Home load)."""
    return compute_stability_for_date(today_local(settings), settings=settings)
