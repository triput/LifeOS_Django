# ==============================================================================
# File: lifeos_app/services/plan.py
# Description: Planner day context assembly
# Component: Services / Plan
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Build timeline data for the Planner surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from lifeos_app.models import CalendarEvent, ScheduledAllocation, SystemEnums
from lifeos_app.services.today import today_items


def calendar_is_live(integration) -> bool:
    """True when integration has real OAuth tokens (not seed placeholder)."""
    if not integration:
        return False
    creds = integration.credentials_json or {}
    if creds.get("seed"):
        return False
    return bool(creds.get("refresh_token") or creds.get("token"))


@dataclass
class PlanBlock:
    """Single row on the planner timeline / calendar grid."""

    kind: str  # allocation | calendar | marker
    start_at: datetime
    end_at: datetime
    title: str
    color: str = "#7080F0"
    item_id: int | None = None
    event_id: int | None = None
    meta: str = ""
    is_all_day: bool = False


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = timezone.make_aware(datetime.combine(day, time.max))
    return start, end


def plan_blocks_for_day(day: date) -> list[PlanBlock]:
    """Merged allocations + blocking calendar events for one day."""
    start, end = _day_bounds(day)
    blocks: list[PlanBlock] = []

    for alloc in (
        ScheduledAllocation.objects.filter(start_at__date=day)
        .select_related("execution_item")
        .order_by("start_at")
    ):
        item = alloc.execution_item
        primary = item.primary_container()
        color = "#7080F0"
        if primary and primary.domain_id:
            color = primary.domain.color
        blocks.append(
            PlanBlock(
                kind="allocation",
                start_at=alloc.start_at,
                end_at=alloc.end_at,
                title=item.title,
                color=color,
                item_id=item.pk,
                meta=alloc.get_source_display(),
            )
        )

    for ev in CalendarEvent.objects.filter(
        is_blocking=True,
        start_at__lt=end,
        end_at__gt=start,
    ).select_related("source_calendar").order_by("start_at"):
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


def provider_calendar_context(provider: str, *, request=None) -> dict:
    """Planner sidebar context for one calendar provider (Google or Microsoft)."""
    from django.urls import reverse

    from lifeos_app.services.calendar_config import (
        get_oauth_config,
        oauth_client_id_hint,
        oauth_configured,
        oauth_setup_message,
        validate_oauth_config,
    )
    from lifeos_app.services.calendar_sync import get_active_integration

    if provider == SystemEnums.CalendarProvider.MICROSOFT:
        provider_label = "Outlook / Microsoft 365"
        settings_anchor = "?tab=calendars#microsoft-calendar-oauth"
        auth_url_name = "calendar-microsoft-auth"
        callback_name = "calendar-microsoft-oauth-callback"
        refresh_url_name = "calendar-microsoft-refresh"
        sync_url_name = "calendar-microsoft-sync"
        panel_id = "plan-calendar-panel-microsoft"
        register_hint = "Register in Azure Entra app registration"
    else:
        provider_label = "Google Calendar"
        settings_anchor = "?tab=calendars#google-calendar-oauth"
        auth_url_name = "calendar-auth"
        callback_name = "calendar-oauth-callback"
        refresh_url_name = "calendar-refresh"
        sync_url_name = "calendar-sync"
        panel_id = "plan-calendar-panel-google"
        register_hint = "Register in Google Cloud Console"

    redirect_uri = ""
    if request is not None:
        redirect_uri = request.build_absolute_uri(reverse(callback_name))
    oauth_ready = oauth_configured(provider=provider, redirect_uri=redirect_uri)
    cfg = get_oauth_config(provider=provider, redirect_uri_override=redirect_uri)
    integration = get_active_integration(provider=provider)
    synced_calendars = []
    if integration and calendar_is_live(integration):
        synced_calendars = list(integration.calendars.all())
    return {
        "provider": provider,
        "provider_label": provider_label,
        "settings_anchor": settings_anchor,
        "auth_url_name": auth_url_name,
        "refresh_url_name": refresh_url_name,
        "sync_url_name": sync_url_name,
        "panel_id": panel_id,
        "register_hint": register_hint,
        "calendar_integration": integration,
        "calendar_live": calendar_is_live(integration),
        "oauth_configured": oauth_ready,
        "oauth_setup_message": oauth_setup_message(provider=provider, redirect_uri=redirect_uri),
        "oauth_redirect_uri": redirect_uri,
        "oauth_config_source": cfg.source,
        "oauth_client_id_hint": oauth_client_id_hint(provider=provider, redirect_uri=redirect_uri),
        "oauth_validation_errors": validate_oauth_config(provider=provider, redirect_uri=redirect_uri),
        "synced_calendars": synced_calendars,
    }


def planner_context(day: date | None = None, *, request=None) -> dict:
    """Template context for SURF-PLAN."""
    if day is None:
        day = timezone.localdate()
    prev_day = day - timedelta(days=1)
    next_day = day + timedelta(days=1)
    calendar_providers = [
        provider_calendar_context(SystemEnums.CalendarProvider.GOOGLE, request=request),
        provider_calendar_context(SystemEnums.CalendarProvider.MICROSOFT, request=request),
    ]
    return {
        "surface": "plan",
        "plan_day": day,
        "plan_prev": prev_day,
        "plan_next": next_day,
        "plan_blocks": plan_blocks_for_day(day),
        "today_items": today_items(),
        "calendar_providers": calendar_providers,
    }
