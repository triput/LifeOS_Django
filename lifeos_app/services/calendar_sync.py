# ==============================================================================
# File: lifeos_app/services/calendar_sync.py
# Description: Google Calendar pull + OAuth scope helpers (ENG-CAL / P5-03)
# Component: Services / Calendar
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Pull external calendar events into CalendarEvent rows for planner + solver."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone

from lifeos_app.models import CalendarEvent, CalendarIntegration, SyncedCalendar
from lifeos_app.services.calendar_config import get_oauth_config

logger = logging.getLogger(__name__)

CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
# Full calendar scope covers calendarList + event insert/patch (P5-03 write).
CALENDAR_FULL_SCOPE = "https://www.googleapis.com/auth/calendar"
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"

_WRITE_SCOPE_MARKERS = (
    CALENDAR_FULL_SCOPE,
    CALENDAR_EVENTS_SCOPE,
)

# Private extended property so pull can skip LifeOS-owned events (no double busy).
LIFEOS_ALLOCATION_PROP = "lifeos_allocation_id"


def google_oauth_scopes() -> list[str]:
    """Scopes for Connect — write when calendar push flag is on."""
    from lifeos_app.models import AppSettings

    if AppSettings.get_solo().calendar_push_enabled:
        return [CALENDAR_FULL_SCOPE]
    return [CALENDAR_READONLY_SCOPE]


def integration_has_write_scope(integration: CalendarIntegration) -> bool:
    """True when stored credentials include event write access."""
    scopes = (integration.credentials_json or {}).get("scopes") or []
    return any(s in _WRITE_SCOPE_MARKERS for s in scopes)


@dataclass
class ParsedCalendarEvent:
    """Normalized event ready for DB upsert."""

    external_id: str
    title: str
    start_at: datetime
    end_at: datetime
    is_all_day: bool
    is_blocking: bool
    description: str = ""


@dataclass
class CalendarSyncResult:
    """Summary of a calendar pull."""

    ok: bool
    created: int = 0
    updated: int = 0
    removed: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)


def get_active_integration(*, provider: str | None = None) -> CalendarIntegration | None:
    """Return the enabled integration row, optionally filtered by provider."""
    qs = CalendarIntegration.objects.filter(sync_enabled=True)
    if provider:
        qs = qs.filter(provider=provider)
    return qs.order_by("-updated_at").first()


def owner_timezone() -> ZoneInfo:
    """Owner IANA timezone from AppSettings."""
    from lifeos_app.models import AppSettings

    try:
        return ZoneInfo(AppSettings.get_solo().timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def parse_google_event(raw: dict[str, Any], tz: ZoneInfo | None = None) -> ParsedCalendarEvent | None:
    """
    Parse a Google Calendar API event dict into normalized datetimes.

    All-day events use local midnight boundaries in the owner timezone.
    """
    tz = tz or owner_timezone()
    external_id = raw.get("id") or ""
    if not external_id:
        return None
    # Skip events LifeOS pushed — allocations already occupy busy time.
    private = ((raw.get("extendedProperties") or {}).get("private")) or {}
    if private.get(LIFEOS_ALLOCATION_PROP):
        return None
    title = raw.get("summary") or "(No title)"
    start = raw.get("start") or {}
    end = raw.get("end") or {}
    is_all_day = "date" in start
    if is_all_day:
        start_date = date.fromisoformat(start["date"])
        end_date = date.fromisoformat(end.get("date", start["date"]))
        start_at = datetime.combine(start_date, time.min, tzinfo=tz)
        end_at = datetime.combine(end_date, time.min, tzinfo=tz)
    else:
        start_at = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(tz)
        end_raw = end.get("dateTime") or start.get("dateTime")
        end_at = datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(tz)
    transparency = raw.get("transparency", "opaque")
    is_blocking = transparency != "transparent"
    description = (raw.get("description") or "").strip()[:10000]
    return ParsedCalendarEvent(
        external_id=external_id,
        title=title[:255],
        start_at=start_at,
        end_at=end_at,
        is_all_day=is_all_day,
        is_blocking=is_blocking,
        description=description,
    )


def upsert_parsed_events(
    integration: CalendarIntegration,
    parsed: list[ParsedCalendarEvent],
    *,
    source_calendar: SyncedCalendar | None = None,
    prune: bool = False,
) -> CalendarSyncResult:
    """Upsert parsed events for one Google calendar source."""
    created = updated = 0
    seen: set[str] = set()
    for event in parsed:
        seen.add(event.external_id)
        if source_calendar:
            lookup = {"source_calendar": source_calendar, "external_id": event.external_id}
        else:
            lookup = {
                "integration": integration,
                "source_calendar": None,
                "external_id": event.external_id,
            }
        _, was_created = CalendarEvent.objects.update_or_create(
            **lookup,
            defaults={
                "integration": integration,
                "title": event.title,
                "description": event.description or "",
                "start_at": event.start_at,
                "end_at": event.end_at,
                "is_all_day": event.is_all_day,
                "is_blocking": event.is_blocking,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1
    removed = 0
    if prune and source_calendar:
        removed, _ = (
            CalendarEvent.objects.filter(source_calendar=source_calendar)
            .exclude(external_id__in=seen)
            .delete()
        )
    label = source_calendar.summary if source_calendar else "calendar"
    return CalendarSyncResult(
        ok=True,
        created=created,
        updated=updated,
        removed=removed,
        message=f"{label}: {len(parsed)} event(s), {created} new, {updated} updated.",
    )


def _build_calendar_service(integration: CalendarIntegration):
    """Return authenticated Google Calendar API client."""
    from googleapiclient.discovery import build

    creds = _credentials_from_integration(integration)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def fetch_google_calendar_list(integration: CalendarIntegration) -> list[dict[str, Any]]:
    """List calendars visible to the connected Google account."""
    service = _build_calendar_service(integration)
    items: list[dict[str, Any]] = []
    page_token = None
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return items


def refresh_synced_calendars(integration: CalendarIntegration) -> int:
    """
    Discover calendars from the connected provider and upsert SyncedCalendar rows.

    On first discovery, enables the primary calendar by default. Existing
    sync_enabled selections are preserved on subsequent refreshes.
    """
    from lifeos_app.models import SystemEnums
    from lifeos_app.services import microsoft_calendar_sync

    if integration.provider == SystemEnums.CalendarProvider.MICROSOFT:
        return microsoft_calendar_sync.refresh_synced_calendars(integration)

    raw_calendars = fetch_google_calendar_list(integration)
    first_discovery = not integration.calendars.exists()
    preserved = set(
        integration.calendars.filter(sync_enabled=True).values_list("calendar_id", flat=True)
    )
    count = 0
    for item in raw_calendars:
        calendar_id = item.get("id") or ""
        if not calendar_id:
            continue
        is_primary = bool(item.get("primary"))
        sync_enabled = calendar_id in preserved
        if first_discovery and is_primary:
            sync_enabled = True
        color = (item.get("backgroundColor") or "#8294AB")[:7]
        existing = SyncedCalendar.objects.filter(
            integration=integration, calendar_id=calendar_id
        ).first()
        defaults = {
            "summary": (item.get("summary") or calendar_id)[:255],
            "is_primary": is_primary,
            "sync_enabled": sync_enabled,
        }
        if not (existing and existing.color_locked):
            defaults["color"] = color
        _, _created = SyncedCalendar.objects.update_or_create(
            integration=integration,
            calendar_id=calendar_id,
            defaults=defaults,
        )
        count += 1
    return count


def enabled_calendars(integration: CalendarIntegration) -> list[SyncedCalendar]:
    """Calendars the owner selected for sync."""
    return list(integration.calendars.filter(sync_enabled=True).order_by("-is_primary", "summary"))


def _credentials_from_integration(integration: CalendarIntegration):
    """Build google.oauth2.credentials.Credentials from stored JSON."""
    from google.oauth2.credentials import Credentials

    data = integration.credentials_json or {}
    if data.get("seed"):
        raise ValueError("Seed integration is not a live Google connection.")
    if not data.get("refresh_token") and not data.get("token"):
        raise ValueError("Calendar credentials missing — connect Google Calendar first.")
    client_id = data.get("client_id") or get_oauth_config().client_id
    client_secret = get_oauth_config().client_secret
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_id,
        client_secret=client_secret,
        scopes=data.get("scopes") or [CALENDAR_READONLY_SCOPE],
    )


def fetch_google_events(
    integration: CalendarIntegration,
    *,
    days_past: int = 1,
    days_future: int = 30,
    calendar_id: str = "primary",
) -> list[dict[str, Any]]:
    """Call Google Calendar API events.list and return raw items."""
    service = _build_calendar_service(integration)
    now = timezone.now()
    time_min = (now - timedelta(days=days_past)).isoformat()
    time_max = (now + timedelta(days=days_future)).isoformat()
    items: list[dict[str, Any]] = []
    page_token = None
    while True:
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            )
            .execute()
        )
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return items


def set_calendar_sync_enabled(synced_calendar: SyncedCalendar, *, enabled: bool) -> None:
    """Toggle whether a discovered calendar is included in pulls."""
    synced_calendar.sync_enabled = enabled
    synced_calendar.save(update_fields=["sync_enabled", "updated_at"])


def set_calendar_color(synced_calendar: SyncedCalendar, *, color: str) -> SyncedCalendar:
    """Set owner override color and lock it against Refresh list overwrites."""
    from lifeos_app.services.appearance import normalize_hex_color

    synced_calendar.color = normalize_hex_color(color, fallback=synced_calendar.color or "#8294AB")
    synced_calendar.color_locked = True
    synced_calendar.save(update_fields=["color", "color_locked", "updated_at"])
    return synced_calendar


def pull_calendar(
    integration: CalendarIntegration | None = None,
    *,
    provider: str | None = None,
    days_past: int = 1,
    days_future: int = 30,
    raw_events: list[dict[str, Any]] | None = None,
    source_calendar: SyncedCalendar | None = None,
) -> CalendarSyncResult:
    """
    Pull calendar events into CalendarEvent rows.

    Pass raw_events in tests to avoid network; otherwise fetches from the provider API.
    When raw_events is None, pulls every SyncedCalendar with sync_enabled=True.
    """
    integration = integration or get_active_integration(provider=provider)
    if not integration:
        return CalendarSyncResult(ok=False, message="No calendar integration configured.")
    if not integration.sync_enabled:
        return CalendarSyncResult(ok=False, message="Calendar sync is disabled.")

    from lifeos_app.models import SystemEnums
    from lifeos_app.services import microsoft_calendar_sync

    if integration.provider == SystemEnums.CalendarProvider.MICROSOFT:
        return microsoft_calendar_sync.pull_microsoft_calendar(
            integration,
            days_past=days_past,
            days_future=days_future,
            raw_events=raw_events,
            source_calendar=source_calendar,
        )

    if (integration.credentials_json or {}).get("seed"):
        return CalendarSyncResult(
            ok=False,
            message="Connect Google Calendar — seed demo events only.",
        )

    tz = owner_timezone()
    try:
        if raw_events is not None:
            parsed: list[ParsedCalendarEvent] = []
            for raw in raw_events:
                event = parse_google_event(raw, tz)
                if event:
                    parsed.append(event)
            result = upsert_parsed_events(
                integration,
                parsed,
                source_calendar=source_calendar,
                prune=bool(source_calendar),
            )
            integration.last_sync_at = timezone.now()
            integration.last_sync_error = ""
            integration.save(update_fields=["last_sync_at", "last_sync_error", "updated_at"])
            return result

        calendars = enabled_calendars(integration)
        if not calendars and integration.calendars.exists():
            return CalendarSyncResult(
                ok=False,
                message="Select one or more calendars below, then Sync now.",
            )
        if not calendars:
            refresh_synced_calendars(integration)
            calendars = enabled_calendars(integration)
        if not calendars:
            return CalendarSyncResult(
                ok=False,
                message="No calendars found on your Google account.",
            )

        total_created = total_updated = total_events = 0
        warnings: list[str] = []
        for cal in calendars:
            try:
                cal_raw = fetch_google_events(
                    integration,
                    days_past=days_past,
                    days_future=days_future,
                    calendar_id=cal.calendar_id,
                )
                parsed = []
                for raw in cal_raw:
                    event = parse_google_event(raw, tz)
                    if event:
                        parsed.append(event)
                sub = upsert_parsed_events(
                    integration,
                    parsed,
                    source_calendar=cal,
                    prune=True,
                )
                total_created += sub.created
                total_updated += sub.updated
                total_events += len(parsed)
            except Exception as exc:  # noqa: BLE001 — continue other calendars
                warnings.append(f"{cal.summary}: {exc}")
                logger.warning("Calendar sync failed for %s: %s", cal.summary, exc)

        if total_events == 0 and warnings:
            msg = "; ".join(warnings)[:500]
            integration.last_sync_error = msg
            integration.save(update_fields=["last_sync_error", "updated_at"])
            return CalendarSyncResult(ok=False, message=msg, warnings=warnings)

        integration.last_sync_at = timezone.now()
        integration.last_sync_error = ""
        integration.save(update_fields=["last_sync_at", "last_sync_error", "updated_at"])
        cal_count = len(calendars)
        message = (
            f"Pulled {total_events} event(s) from {cal_count} calendar(s): "
            f"{total_created} new, {total_updated} updated."
        )
        if warnings:
            message += f" Warnings: {'; '.join(warnings[:2])}"
        return CalendarSyncResult(
            ok=True,
            created=total_created,
            updated=total_updated,
            message=message,
            warnings=warnings,
        )
    except Exception as exc:  # noqa: BLE001 — persist sync error on integration row
        msg = str(exc)
        logger.warning("Calendar sync failed: %s", msg)
        integration.last_sync_error = msg[:500]
        integration.save(update_fields=["last_sync_error", "updated_at"])
        return CalendarSyncResult(ok=False, message=msg, warnings=[msg])
