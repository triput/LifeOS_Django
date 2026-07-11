# ==============================================================================
# File: lifeos_app/services/analytics.py
# Description: Velocity / focus / stability history for SURF-ANALYTICS
# Component: Services / Analytics
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Historical series for Analytics — never rendered on Home (FR-UI-046–048)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Sum

from lifeos_app.models import AppSettings, FocusSession, StabilitySnapshot, SystemEnums
from lifeos_app.services.stability import ensure_today_stability, local_day_bounds, today_local

WINDOW_CHOICES: tuple[tuple[int, str], ...] = (
    (7, "7 days"),
    (14, "14 days"),
    (28, "28 days"),
    (90, "90 days"),
)
DEFAULT_WINDOW_DAYS = 14


@dataclass
class DaySeriesPoint:
    """One local calendar day of analytics metrics."""

    local_date: date
    index_score: int
    band: str
    completions_count: int
    focus_seconds: int
    planned_minutes: int
    streak_days: int
    completion_target: int
    focus_minutes_target: int
    has_snapshot: bool

    @property
    def focus_minutes(self) -> float:
        return self.focus_seconds / 60.0

    @property
    def completion_pct(self) -> int:
        if self.completion_target <= 0:
            return 0
        return max(0, min(100, int(round(100.0 * self.completions_count / self.completion_target))))

    @property
    def focus_pct(self) -> int:
        denom = float(self.planned_minutes or self.focus_minutes_target or 1)
        return max(0, min(100, int(round(100.0 * self.focus_minutes / denom))))

    @property
    def band_label(self) -> str:
        return dict(SystemEnums.StabilityBand.choices).get(self.band, self.band)


@dataclass
class AnalyticsSummary:
    """Rollup totals for the selected window."""

    days: int
    completions_total: int
    focus_seconds_total: int
    stable_days: int
    behind_days: int
    overloaded_days: int
    avg_score: float
    completion_target: int
    focus_minutes_target: int


def parse_window_days(raw: str | int | None) -> int:
    """Clamp window to allowed choices."""
    try:
        days = int(raw) if raw is not None and str(raw).strip() else DEFAULT_WINDOW_DAYS
    except (TypeError, ValueError):
        days = DEFAULT_WINDOW_DAYS
    allowed = {c[0] for c in WINDOW_CHOICES}
    return days if days in allowed else DEFAULT_WINDOW_DAYS


def _focus_seconds_for_day(local_date: date, settings: AppSettings) -> int:
    """Sum closed FocusSession duration ending on local_date (+ open if started that day)."""
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
        from django.utils import timezone

        open_extra = max(0, int((timezone.now() - open_sess.started_at).total_seconds()))
        open_extra += int(open_sess.duration_seconds or 0)
    return int(closed) + int(open_extra)


def build_day_series(*, days: int = DEFAULT_WINDOW_DAYS, settings: AppSettings | None = None) -> list[DaySeriesPoint]:
    """
    Chronological series oldest→newest for the last `days` local dates.

    Prefers StabilitySnapshot; fills focus from FocusSession when snapshot missing.
    Ensures today's snapshot exists so the series is live.
    """
    settings = settings or AppSettings.get_solo()
    ensure_today_stability(settings=settings)
    end = today_local(settings)
    start = end - timedelta(days=days - 1)
    snaps = {
        s.date: s
        for s in StabilitySnapshot.objects.filter(date__gte=start, date__lte=end)
    }
    completion_target = max(1, int(settings.daily_completion_target or 1))
    focus_target = max(1, int(settings.daily_focus_minutes_target or 1))

    series: list[DaySeriesPoint] = []
    cursor = start
    while cursor <= end:
        snap = snaps.get(cursor)
        if snap:
            series.append(
                DaySeriesPoint(
                    local_date=cursor,
                    index_score=int(snap.index_score),
                    band=snap.band,
                    completions_count=int(snap.completions_count),
                    focus_seconds=int(snap.focus_seconds),
                    planned_minutes=int(snap.planned_minutes),
                    streak_days=int(snap.streak_days),
                    completion_target=completion_target,
                    focus_minutes_target=focus_target,
                    has_snapshot=True,
                )
            )
        else:
            focus_s = _focus_seconds_for_day(cursor, settings)
            series.append(
                DaySeriesPoint(
                    local_date=cursor,
                    index_score=0,
                    band="",
                    completions_count=0,
                    focus_seconds=focus_s,
                    planned_minutes=focus_target,
                    streak_days=0,
                    completion_target=completion_target,
                    focus_minutes_target=focus_target,
                    has_snapshot=False,
                )
            )
        cursor += timedelta(days=1)
    return series


def summarize_series(series: list[DaySeriesPoint]) -> AnalyticsSummary:
    """Aggregate totals / band counts for the window."""
    if not series:
        settings = AppSettings.get_solo()
        return AnalyticsSummary(
            days=0,
            completions_total=0,
            focus_seconds_total=0,
            stable_days=0,
            behind_days=0,
            overloaded_days=0,
            avg_score=0.0,
            completion_target=max(1, int(settings.daily_completion_target or 1)),
            focus_minutes_target=max(1, int(settings.daily_focus_minutes_target or 1)),
        )
    scored = [p for p in series if p.has_snapshot]
    avg = (sum(p.index_score for p in scored) / len(scored)) if scored else 0.0
    return AnalyticsSummary(
        days=len(series),
        completions_total=sum(p.completions_count for p in series),
        focus_seconds_total=sum(p.focus_seconds for p in series),
        stable_days=sum(1 for p in series if p.band == SystemEnums.StabilityBand.STABLE),
        behind_days=sum(1 for p in series if p.band == SystemEnums.StabilityBand.BEHIND),
        overloaded_days=sum(1 for p in series if p.band == SystemEnums.StabilityBand.OVERLOADED),
        avg_score=round(avg, 1),
        completion_target=series[-1].completion_target,
        focus_minutes_target=series[-1].focus_minutes_target,
    )


def build_analytics_page(*, days: int | None = None) -> dict:
    """Context for `/canvas/analytics/`."""
    window = parse_window_days(days)
    series = build_day_series(days=window)
    summary = summarize_series(series)
    max_focus = max((p.focus_seconds for p in series), default=1) or 1
    max_completions = max((p.completions_count for p in series), default=1) or 1
    # Scale bars relative to window max (and at least target for completions)
    max_completions = max(max_completions, summary.completion_target)
    return {
        "surface": "analytics",
        "window_days": window,
        "window_choices": WINDOW_CHOICES,
        "series": series,
        "series_newest_first": list(reversed(series)),
        "summary": summary,
        "max_focus_seconds": max_focus,
        "max_completions": max_completions,
        "range_start": series[0].local_date if series else None,
        "range_end": series[-1].local_date if series else None,
    }
