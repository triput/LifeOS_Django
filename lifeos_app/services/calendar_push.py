# ==============================================================================
# File: lifeos_app/services/calendar_push.py
# Description: Feature-flagged Google Calendar push for allocations (P5-03)
# Component: Services / Calendar
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Push ScheduledAllocation rows to Google Calendar when the owner enables it.

Pull stays the source of truth for external busy time. Pushed events are tagged
with a private extended property so subsequent pulls skip them (no double busy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from django.utils import timezone

from lifeos_app.models import AppSettings, ScheduledAllocation, SyncedCalendar, SystemEnums
from lifeos_app.services.calendar_sync import (
    LIFEOS_ALLOCATION_PROP,
    _build_calendar_service,
    enabled_calendars,
    get_active_integration,
    integration_has_write_scope,
    owner_timezone,
)

logger = logging.getLogger(__name__)


@dataclass
class PushResult:
    """Summary of one or more allocation pushes."""

    ok: bool
    pushed: int = 0
    updated: int = 0
    skipped: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)


def calendar_push_enabled() -> bool:
    """Owner feature flag for two-way Google push."""
    return bool(AppSettings.get_solo().calendar_push_enabled)


def resolve_push_calendar(integration=None) -> SyncedCalendar | None:
    """Prefer primary sync-enabled Google calendar; else first enabled."""
    integration = integration or get_active_integration(
        provider=SystemEnums.CalendarProvider.GOOGLE
    )
    if not integration:
        return None
    calendars = enabled_calendars(integration)
    if not calendars:
        return None
    for cal in calendars:
        if cal.is_primary:
            return cal
    return calendars[0]


def _event_body(allocation: ScheduledAllocation) -> dict[str, Any]:
    """Google Calendar event payload for an allocation."""
    tz = owner_timezone()
    item = allocation.execution_item
    start = allocation.start_at.astimezone(tz)
    end = allocation.end_at.astimezone(tz)
    return {
        "summary": (item.title or "LifeOS block")[:1024],
        "description": f"LifeOS allocation · item #{item.pk}",
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": str(tz),
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": str(tz),
        },
        "extendedProperties": {
            "private": {LIFEOS_ALLOCATION_PROP: str(allocation.pk)},
        },
    }


def push_allocation(
    allocation: ScheduledAllocation,
    *,
    service: Any | None = None,
    push_calendar: SyncedCalendar | None = None,
) -> PushResult:
    """Insert or patch one allocation on Google. No-op when flag is off."""
    if not calendar_push_enabled():
        return PushResult(ok=True, skipped=1, message="Calendar push disabled.")

    integration = get_active_integration(provider=SystemEnums.CalendarProvider.GOOGLE)
    if not integration or not integration.sync_enabled:
        return PushResult(ok=False, skipped=1, message="Google Calendar not connected.")
    if (integration.credentials_json or {}).get("seed"):
        return PushResult(ok=False, skipped=1, message="Seed integration cannot push.")
    if not integration_has_write_scope(integration):
        return PushResult(
            ok=False,
            skipped=1,
            message=(
                "Reconnect Google Calendar to grant write access "
                "(enable push in Settings, then Planner → Connect)."
            ),
        )

    target = push_calendar or allocation.push_calendar or resolve_push_calendar(integration)
    if not target:
        return PushResult(
            ok=False,
            skipped=1,
            message="Select a Google calendar to sync before pushing allocations.",
        )

    try:
        svc = service or _build_calendar_service(integration)
        body = _event_body(allocation)
        if allocation.external_event_id:
            svc.events().patch(
                calendarId=target.calendar_id,
                eventId=allocation.external_event_id,
                body=body,
            ).execute()
            if allocation.push_calendar_id != target.pk:
                allocation.push_calendar = target
                allocation.save(update_fields=["push_calendar"])
            return PushResult(
                ok=True,
                updated=1,
                message=f"Updated Google event for {allocation.execution_item.title!r}.",
            )

        created = (
            svc.events()
            .insert(calendarId=target.calendar_id, body=body)
            .execute()
        )
        allocation.external_event_id = created.get("id") or ""
        allocation.push_calendar = target
        allocation.save(update_fields=["external_event_id", "push_calendar"])
        return PushResult(
            ok=True,
            pushed=1,
            message=f"Pushed {allocation.execution_item.title!r} to Google.",
        )
    except Exception as exc:  # noqa: BLE001 — surface to caller / schedule message
        logger.warning("Calendar push failed for allocation %s: %s", allocation.pk, exc)
        return PushResult(ok=False, skipped=1, message=str(exc)[:300], warnings=[str(exc)])


def push_pending_allocations(
    *,
    service_factory: Callable[[Any], Any] | None = None,
) -> PushResult:
    """Insert/patch future allocations onto the push-target Google calendar."""
    if not calendar_push_enabled():
        return PushResult(ok=True, message="")

    integration = get_active_integration(provider=SystemEnums.CalendarProvider.GOOGLE)
    if not integration:
        return PushResult(ok=False, message="Google Calendar not connected.")
    if not integration_has_write_scope(integration):
        return PushResult(
            ok=False,
            message=(
                "Calendar push on — reconnect Google for write scope "
                "(Planner → Connect)."
            ),
        )

    target = resolve_push_calendar(integration)
    if not target:
        return PushResult(ok=False, message="No sync-enabled Google calendar for push.")

    try:
        service = (
            service_factory(integration)
            if service_factory
            else _build_calendar_service(integration)
        )
    except Exception as exc:  # noqa: BLE001
        return PushResult(ok=False, message=str(exc)[:300])

    now = timezone.now()
    qs = (
        ScheduledAllocation.objects.filter(end_at__gte=now)
        .select_related("execution_item", "push_calendar")
        .order_by("start_at")
    )
    pushed = updated = skipped = 0
    warnings: list[str] = []
    for alloc in qs:
        result = push_allocation(alloc, service=service, push_calendar=target)
        pushed += result.pushed
        updated += result.updated
        skipped += result.skipped
        if not result.ok and result.message:
            warnings.append(result.message)

    parts = []
    if pushed:
        parts.append(f"pushed {pushed}")
    if updated:
        parts.append(f"updated {updated}")
    if skipped and not parts:
        parts.append(f"skipped {skipped}")
    message = ("Google: " + ", ".join(parts) + ".") if parts else ""
    if warnings and not parts:
        message = warnings[0]
    return PushResult(
        ok=not warnings or bool(parts),
        pushed=pushed,
        updated=updated,
        skipped=skipped,
        message=message,
        warnings=warnings[:5],
    )
