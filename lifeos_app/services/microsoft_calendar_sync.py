# ==============================================================================
# File: lifeos_app/services/microsoft_calendar_sync.py
# Description: Microsoft Graph calendar read-only pull (ENG-CAL-MS)
# Component: Services / Calendar
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Pull Outlook / Microsoft 365 calendars into CalendarEvent rows."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests
from django.utils import timezone

from lifeos_app.models import CalendarIntegration, SyncedCalendar, SystemEnums
from lifeos_app.services.calendar_config import get_oauth_config
from lifeos_app.services.calendar_sync import (
    CalendarSyncResult,
    ParsedCalendarEvent,
    enabled_calendars,
    owner_timezone,
    upsert_parsed_events,
)
from lifeos_app.services.microsoft_calendar_oauth import MICROSOFT_GRAPH_BASE, MICROSOFT_TOKEN_URL

logger = logging.getLogger(__name__)


def parse_microsoft_event(raw: dict[str, Any], tz: ZoneInfo | None = None) -> ParsedCalendarEvent | None:
    """Parse a Microsoft Graph event dict into normalized datetimes."""
    import re
    from html import unescape

    tz = tz or owner_timezone()
    external_id = raw.get("id") or ""
    if not external_id:
        return None
    title = (raw.get("subject") or "(No title)")[:255]
    start = raw.get("start") or {}
    end = raw.get("end") or {}
    is_all_day = bool(raw.get("isAllDay"))
    if is_all_day:
        start_raw = start.get("dateTime", "")[:10]
        end_raw = (end.get("dateTime") or start.get("dateTime") or "")[:10]
        if not start_raw:
            return None
        start_at = datetime.fromisoformat(start_raw).replace(tzinfo=tz)
        end_at = datetime.fromisoformat(end_raw or start_raw).replace(tzinfo=tz)
    else:
        start_dt = start.get("dateTime")
        end_dt = end.get("dateTime") or start_dt
        if not start_dt:
            return None
        start_at = datetime.fromisoformat(start_dt.replace("Z", "+00:00")).astimezone(tz)
        end_at = datetime.fromisoformat(end_dt.replace("Z", "+00:00")).astimezone(tz)
    show_as = (raw.get("showAs") or "busy").lower()
    is_blocking = show_as not in {"free", "workingelsewhere"}
    description = (raw.get("bodyPreview") or "").strip()
    if not description:
        body = raw.get("body") or {}
        content = (body.get("content") or "").strip()
        if content:
            description = unescape(re.sub(r"<[^>]+>", " ", content))
            description = re.sub(r"\s+", " ", description).strip()
    description = description[:10000]
    return ParsedCalendarEvent(
        external_id=external_id,
        title=title,
        start_at=start_at,
        end_at=end_at,
        is_all_day=is_all_day,
        is_blocking=is_blocking,
        description=description,
    )


def _access_token(integration: CalendarIntegration) -> str:
    """Return a valid Graph access token, refreshing when needed."""
    data = integration.credentials_json or {}
    if data.get("seed"):
        raise ValueError("Seed integration is not a live Microsoft connection.")
    refresh_token = data.get("refresh_token")
    token = data.get("token")
    if not refresh_token and not token:
        raise ValueError("Calendar credentials missing — connect Outlook first.")
    config = get_oauth_config(provider=SystemEnums.CalendarProvider.MICROSOFT)
    if refresh_token:
        response = requests.post(
            MICROSOFT_TOKEN_URL,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": " ".join(data.get("scopes") or ["Calendars.Read", "offline_access"]),
            },
            timeout=30,
        )
        if response.status_code < 400:
            payload = response.json()
            data["token"] = payload.get("access_token")
            if payload.get("refresh_token"):
                data["refresh_token"] = payload.get("refresh_token")
            integration.credentials_json = data
            integration.save(update_fields=["credentials_json", "updated_at"])
            token = data.get("token")
    if not token:
        raise ValueError("Unable to refresh Microsoft access token.")
    return token


def _graph_get(integration: CalendarIntegration, path: str, *, params: dict | None = None) -> dict:
    token = _access_token(integration)
    response = requests.get(
        f"{MICROSOFT_GRAPH_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30,
    )
    if response.status_code >= 400:
        raise ValueError(response.text[:300])
    return response.json()


def fetch_microsoft_calendar_list(integration: CalendarIntegration) -> list[dict[str, Any]]:
    """List calendars visible to the connected Microsoft account."""
    items: list[dict[str, Any]] = []
    path = "/me/calendars"
    while path:
        payload = _graph_get(integration, path if path.startswith("/") else f"/{path}")
        items.extend(payload.get("value", []))
        next_link = payload.get("@odata.nextLink")
        if next_link and MICROSOFT_GRAPH_BASE in next_link:
            path = next_link.split(MICROSOFT_GRAPH_BASE, 1)[1]
        else:
            path = ""
    return items


def refresh_synced_calendars(integration: CalendarIntegration) -> int:
    """Discover calendars from Microsoft Graph and upsert SyncedCalendar rows."""
    raw_calendars = fetch_microsoft_calendar_list(integration)
    first_discovery = not integration.calendars.exists()
    preserved = set(
        integration.calendars.filter(sync_enabled=True).values_list("calendar_id", flat=True)
    )
    count = 0
    for item in raw_calendars:
        calendar_id = item.get("id") or ""
        if not calendar_id:
            continue
        is_primary = bool(item.get("isDefaultCalendar"))
        sync_enabled = calendar_id in preserved
        if first_discovery and is_primary:
            sync_enabled = True
        color = (item.get("hexColor") or "#8294AB")[:7]
        if color and not color.startswith("#"):
            color = f"#{color}"[:7]
        existing = SyncedCalendar.objects.filter(
            integration=integration, calendar_id=calendar_id
        ).first()
        defaults = {
            "summary": (item.get("name") or calendar_id)[:255],
            "is_primary": is_primary,
            "sync_enabled": sync_enabled,
        }
        if not (existing and existing.color_locked):
            defaults["color"] = color
        SyncedCalendar.objects.update_or_create(
            integration=integration,
            calendar_id=calendar_id,
            defaults=defaults,
        )
        count += 1
    return count


def fetch_microsoft_events(
    integration: CalendarIntegration,
    *,
    days_past: int = 1,
    days_future: int = 30,
    calendar_id: str,
) -> list[dict[str, Any]]:
    """Call Graph calendarView and return raw event dicts."""
    now = timezone.now()
    start = (now - timedelta(days=days_past)).isoformat()
    end = (now + timedelta(days=days_future)).isoformat()
    items: list[dict[str, Any]] = []
    path = f"/me/calendars/{calendar_id}/calendarView"
    params: dict[str, str] | None = {"startDateTime": start, "endDateTime": end}
    while path:
        payload = _graph_get(integration, path if path.startswith("/") else f"/{path}", params=params)
        params = None
        items.extend(payload.get("value", []))
        next_link = payload.get("@odata.nextLink")
        if next_link and MICROSOFT_GRAPH_BASE in next_link:
            path = next_link.split(MICROSOFT_GRAPH_BASE, 1)[1]
        else:
            path = ""
    return items


def pull_microsoft_calendar(
    integration: CalendarIntegration,
    *,
    days_past: int = 1,
    days_future: int = 30,
    raw_events: list[dict[str, Any]] | None = None,
    source_calendar: SyncedCalendar | None = None,
) -> CalendarSyncResult:
    """Pull Microsoft Graph events into CalendarEvent rows."""
    if not integration.sync_enabled:
        return CalendarSyncResult(ok=False, message="Calendar sync is disabled.")
    if (integration.credentials_json or {}).get("seed"):
        return CalendarSyncResult(
            ok=False,
            message="Connect Outlook — seed demo events only.",
        )

    tz = owner_timezone()
    try:
        if raw_events is not None:
            parsed: list[ParsedCalendarEvent] = []
            for raw in raw_events:
                event = parse_microsoft_event(raw, tz)
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
                message="No calendars found on your Microsoft account.",
            )

        total_created = total_updated = total_events = 0
        warnings: list[str] = []
        for cal in calendars:
            try:
                cal_raw = fetch_microsoft_events(
                    integration,
                    days_past=days_past,
                    days_future=days_future,
                    calendar_id=cal.calendar_id,
                )
                parsed = []
                for raw in cal_raw:
                    event = parse_microsoft_event(raw, tz)
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
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{cal.summary}: {exc}")
                logger.warning("Microsoft calendar sync failed for %s: %s", cal.summary, exc)

        if total_events == 0 and warnings:
            msg = "; ".join(warnings)[:500]
            integration.last_sync_error = msg
            integration.save(update_fields=["last_sync_error", "updated_at"])
            return CalendarSyncResult(ok=False, message=msg, warnings=warnings)

        integration.last_sync_at = timezone.now()
        integration.last_sync_error = ""
        integration.save(update_fields=["last_sync_at", "last_sync_error", "updated_at"])
        message = (
            f"Pulled {total_events} event(s) from {len(calendars)} calendar(s): "
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
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        logger.warning("Microsoft calendar sync failed: %s", msg)
        integration.last_sync_error = msg[:500]
        integration.save(update_fields=["last_sync_error", "updated_at"])
        return CalendarSyncResult(ok=False, message=msg, warnings=[msg])
