# ==============================================================================
# File: lifeos_app/services/notify.py
# Description: Outbound reminder sweep (ENG-NOTIFY) with ntfy/Gotify adapters
# Component: Services / Notifications
# Version: 1.2 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-11
# ==============================================================================
"""Reminder dispatch sweep — webhook when configured, durable log always."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone

from lifeos_app.models import AppSettings, ReminderDispatch, SystemEnums
from lifeos_app.services.settings_surface import SaveResult

_KIND_LABELS = {
    "DUE_APPROACHING": "Due soon",
    "ALLOCATION_START": "Starting now",
    "OVERDUE": "Overdue",
    "TEST": "Test",
}

_DISPATCH_CHANNEL = {
    SystemEnums.NotificationChannel.NTFY: "webhook_ntfy",
    SystemEnums.NotificationChannel.GOTIFY: "webhook_gotify",
    SystemEnums.NotificationChannel.RAW_JSON: "webhook_raw",
}


@dataclass
class SweepResult:
    """Counts from a reminder sweep pass."""

    examined: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class ReminderPayload:
    """Normalized reminder body before channel-specific encoding."""

    title: str
    kind: str
    item_id: int | None
    dedupe_key: str
    fire_at: str


@dataclass(frozen=True)
class WebhookRequest:
    """HTTP request shape for outbound webhook delivery."""

    url: str
    data: bytes
    headers: dict[str, str]
    method: str = "POST"


def pending_alert_count() -> int:
    """In-app glyph count — due pending reminders."""
    now = timezone.now()
    return ReminderDispatch.objects.filter(
        status=SystemEnums.ReminderDispatchStatus.PENDING,
        fire_at__lte=now,
    ).filter(Q(snooze_until__isnull=True) | Q(snooze_until__lte=now)).count()


def _kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind.replace("_", " ").title())


def _reminder_message(payload: ReminderPayload) -> str:
    label = _kind_label(payload.kind)
    return f"{label}: {payload.title}"


def _resolve_channel(channel: str) -> str:
    valid = {c.value for c in SystemEnums.NotificationChannel}
    if channel in valid:
        return channel
    return SystemEnums.NotificationChannel.NTFY


def dispatch_channel_name(channel: str) -> str:
    """Map AppSettings channel to ReminderDispatch.channel value."""
    resolved = _resolve_channel(channel)
    return _DISPATCH_CHANNEL.get(resolved, "webhook_ntfy")


def build_webhook_request(
    *,
    channel: str,
    url: str,
    token: str,
    payload: ReminderPayload,
) -> WebhookRequest:
    """Build provider-specific HTTP request for a reminder payload."""
    resolved = _resolve_channel(channel)
    if resolved == SystemEnums.NotificationChannel.NTFY:
        headers = {
            "Title": _kind_label(payload.kind),
            "Tags": "lifeos," + payload.kind.lower(),
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return WebhookRequest(
            url=url,
            data=_reminder_message(payload).encode("utf-8"),
            headers=headers,
        )
    if resolved == SystemEnums.NotificationChannel.GOTIFY:
        target = url.rstrip("/")
        if not target.endswith("/message"):
            target = f"{target}/message"
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Gotify-Key"] = token
        body = {
            "title": _kind_label(payload.kind),
            "message": _reminder_message(payload),
            "priority": 5 if payload.kind == "OVERDUE" else 4,
        }
        return WebhookRequest(
            url=target,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
        )
    # Raw JSON — custom bots and future adapters
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {
        "title": payload.title,
        "kind": payload.kind,
        "item_id": payload.item_id,
        "dedupe_key": payload.dedupe_key,
        "fire_at": payload.fire_at,
    }
    return WebhookRequest(
        url=url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
    )


def _execute_webhook_request(request: WebhookRequest) -> None:
    req = urllib.request.Request(
        request.url,
        data=request.data,
        headers=request.headers,
        method=request.method,
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status >= 400:
            raise urllib.error.HTTPError(
                request.url, resp.status, "webhook failed", resp.headers, None
            )


def deliver_webhook(
    *,
    channel: str,
    url: str,
    token: str,
    payload: ReminderPayload,
) -> None:
    """POST a reminder payload using the configured channel adapter."""
    request = build_webhook_request(channel=channel, url=url, token=token, payload=payload)
    _execute_webhook_request(request)


def sweep_reminders() -> SweepResult:
    """
    Plan missing ETA rows (safety net), then send due pending reminders.

    When notifications are disabled or webhook missing, marks skipped with note.
    Quiet hours leave rows PENDING for the next sweep.
    """
    from lifeos_app.services.reminders import in_quiet_hours, plan_safety_net

    plan_safety_net()

    settings = AppSettings.get_solo()
    now = timezone.now()
    qs = ReminderDispatch.objects.filter(
        status=SystemEnums.ReminderDispatchStatus.PENDING,
        fire_at__lte=now,
    ).filter(Q(snooze_until__isnull=True) | Q(snooze_until__lte=now))

    result = SweepResult(examined=qs.count())
    if in_quiet_hours(settings, now=now):
        result.skipped = result.examined
        return result

    for dispatch in qs.select_related("execution_item"):
        if not settings.notifications_enabled:
            dispatch.status = SystemEnums.ReminderDispatchStatus.FAILED
            dispatch.last_error = "notifications_disabled"
            dispatch.save(update_fields=["status", "last_error", "updated_at"])
            result.skipped += 1
            continue
        if not settings.notification_webhook_url:
            dispatch.status = SystemEnums.ReminderDispatchStatus.FAILED
            dispatch.last_error = "webhook_not_configured"
            dispatch.save(update_fields=["status", "last_error", "updated_at"])
            result.skipped += 1
            continue
        payload = ReminderPayload(
            title=dispatch.execution_item.title,
            kind=dispatch.kind,
            item_id=dispatch.execution_item_id,
            dedupe_key=dispatch.dedupe_key,
            fire_at=dispatch.fire_at.isoformat(),
        )
        channel_name = dispatch_channel_name(settings.notification_channel)
        try:
            deliver_webhook(
                channel=settings.notification_channel,
                url=settings.notification_webhook_url,
                token=settings.notification_webhook_token,
                payload=payload,
            )
            dispatch.status = SystemEnums.ReminderDispatchStatus.SENT
            dispatch.sent_at = now
            dispatch.channel = channel_name
            dispatch.last_error = ""
            dispatch.save(
                update_fields=["status", "sent_at", "channel", "last_error", "updated_at"]
            )
            result.sent += 1
        except Exception as exc:  # noqa: BLE001 — log delivery failure on row
            dispatch.status = SystemEnums.ReminderDispatchStatus.FAILED
            dispatch.last_error = str(exc)[:500]
            dispatch.save(update_fields=["status", "last_error", "updated_at"])
            result.failed += 1
    return result


def send_test_webhook() -> SaveResult:
    """Send a test payload using current AppSettings webhook configuration."""
    settings = AppSettings.get_solo()
    if not settings.notification_webhook_url:
        return SaveResult(ok=False, message="Set a webhook URL first.")
    channel = _resolve_channel(settings.notification_channel)
    payload = ReminderPayload(
        title="LifeOS test notification",
        kind="TEST",
        item_id=None,
        dedupe_key="lifeos-webhook-test",
        fire_at=timezone.now().isoformat(),
    )
    try:
        deliver_webhook(
            channel=settings.notification_channel,
            url=settings.notification_webhook_url,
            token=settings.notification_webhook_token,
            payload=payload,
        )
        label = dict(SystemEnums.NotificationChannel.choices).get(channel, channel)
        return SaveResult(ok=True, message=f"Test {label} webhook delivered successfully.")
    except Exception as exc:  # noqa: BLE001
        return SaveResult(ok=False, message=f"Webhook test failed: {exc}")
