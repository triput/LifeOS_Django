# ==============================================================================
# File: lifeos_app/services/reminders.py
# Description: Plan ReminderDispatch rows on due/allocation changes (P5-05)
# Component: Services / Notifications
# Version: 1.0 (Gold Master)
# Created: 2026-07-11
# Last Update: 2026-07-11
# ==============================================================================
"""Create / re-arm ETA reminder rows; Celery ETA + Beat sweep as safety net.

FR-NOTIFY-002/004/005 — plan on due_at / allocation create-update; cancel and
re-arm when times change; unique dedupe_key per lead bucket.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

from django.utils import timezone

from lifeos_app.models import (
    AppSettings,
    ExecutionItem,
    ReminderDispatch,
    ScheduledAllocation,
    SystemEnums,
)

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = {
    SystemEnums.ItemStatus.PLANNED,
    SystemEnums.ItemStatus.IN_PROGRESS,
    SystemEnums.ItemStatus.BLOCKED,
}

_OPEN_DISPATCH = {
    SystemEnums.ReminderDispatchStatus.PENDING,
    SystemEnums.ReminderDispatchStatus.SNOOZED,
}


@dataclass
class PlanResult:
    """Counts from a reminder planning pass."""

    created: int = 0
    cancelled: int = 0
    skipped: int = 0
    enqueued: int = 0
    warnings: list[str] = field(default_factory=list)


def lead_minutes_list(settings: AppSettings | None = None) -> list[int]:
    """Configured lead times (primary + optional second), unique descending."""
    solo = settings or AppSettings.get_solo()
    leads = [max(1, int(solo.reminder_lead_minutes or 15))]
    second = solo.reminder_second_lead_minutes
    if second is not None and int(second) > 0:
        leads.append(int(second))
    # Unique, longest lead first (plan far-out then near).
    return sorted(set(leads), reverse=True)


def item_eligible_for_reminders(
    item: ExecutionItem,
    settings: AppSettings | None = None,
) -> bool:
    """FR-NOTIFY-003 status / priority / deleted filters."""
    solo = settings or AppSettings.get_solo()
    if item.is_deleted:
        return False
    if item.status == SystemEnums.ItemStatus.COMPLETED:
        return False
    if item.priority > int(solo.reminder_min_priority):
        return False
    if item.status in _ACTIVE_STATUSES:
        return True
    if item.status == SystemEnums.ItemStatus.BACKLOG:
        return bool(solo.remind_backlog_with_due and item.due_at)
    if item.status == SystemEnums.ItemStatus.INBOX:
        return bool(solo.remind_inbox_with_due and item.due_at)
    return False


def _dedupe_key(
    *,
    item_id: int,
    kind: str,
    lead_minutes: int,
    allocation_id: int | None = None,
    fire_bucket: str,
) -> str:
    """Stable unique key — FR-NOTIFY-005."""
    alloc = f":a{allocation_id}" if allocation_id else ""
    return f"{kind}:i{item_id}{alloc}:L{lead_minutes}:{fire_bucket}"


def _fire_bucket(fire_at: datetime) -> str:
    """Minute-resolution bucket so re-arms with same wall clock collide cleanly."""
    aware = fire_at if timezone.is_aware(fire_at) else timezone.make_aware(fire_at)
    return aware.strftime("%Y%m%d%H%M")


def cancel_open_dispatches(
    *,
    item: ExecutionItem | None = None,
    allocation: ScheduledAllocation | None = None,
    kinds: Iterable[str] | None = None,
) -> int:
    """Cancel PENDING/SNOOZED rows for an item and/or allocation."""
    qs = ReminderDispatch.objects.filter(status__in=_OPEN_DISPATCH)
    if item is not None:
        qs = qs.filter(execution_item=item)
    if allocation is not None:
        qs = qs.filter(scheduled_allocation=allocation)
    if kinds is not None:
        qs = qs.filter(kind__in=list(kinds))
    return qs.update(
        status=SystemEnums.ReminderDispatchStatus.CANCELLED,
        updated_at=timezone.now(),
    )


def _enqueue_eta(dispatch: ReminderDispatch) -> bool:
    """Schedule Celery ETA fire when not eager / fire_at in the future."""
    from django.conf import settings as dj_settings

    if getattr(dj_settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return False
    now = timezone.now()
    if dispatch.fire_at <= now:
        return False
    try:
        from lifeos_app.tasks import fire_reminder_task

        fire_reminder_task.apply_async(args=[dispatch.pk], eta=dispatch.fire_at)
        return True
    except Exception as exc:  # noqa: BLE001 — Beat sweep remains the safety net
        logger.warning("ETA enqueue failed for dispatch %s: %s", dispatch.pk, exc)
        return False


def _upsert_dispatch(
    *,
    item: ExecutionItem,
    kind: str,
    fire_at: datetime,
    lead_minutes: int,
    allocation: ScheduledAllocation | None = None,
    channel: str = "webhook_ntfy",
) -> tuple[ReminderDispatch | None, bool]:
    """Create or refresh a PENDING dispatch. Returns (row, created)."""
    if fire_at is None:
        return None, False
    bucket = _fire_bucket(fire_at)
    key = _dedupe_key(
        item_id=item.pk,
        kind=kind,
        lead_minutes=lead_minutes,
        allocation_id=allocation.pk if allocation else None,
        fire_bucket=bucket,
    )
    existing = ReminderDispatch.objects.filter(dedupe_key=key).first()
    if existing:
        if existing.status == SystemEnums.ReminderDispatchStatus.SENT:
            return existing, False
        if existing.status in _OPEN_DISPATCH:
            return existing, False
        # Re-arm cancelled/failed with same key.
        existing.status = SystemEnums.ReminderDispatchStatus.PENDING
        existing.fire_at = fire_at
        existing.snooze_until = None
        existing.last_error = ""
        existing.sent_at = None
        existing.scheduled_allocation = allocation
        existing.save(
            update_fields=[
                "status",
                "fire_at",
                "snooze_until",
                "last_error",
                "sent_at",
                "scheduled_allocation",
                "updated_at",
            ]
        )
        return existing, True

    row = ReminderDispatch.objects.create(
        execution_item=item,
        scheduled_allocation=allocation,
        kind=kind,
        fire_at=fire_at,
        channel=channel,
        dedupe_key=key,
        status=SystemEnums.ReminderDispatchStatus.PENDING,
    )
    return row, True


def plan_due_reminders(
    item: ExecutionItem,
    *,
    settings: AppSettings | None = None,
    enqueue_eta: bool = True,
) -> PlanResult:
    """Cancel prior due/overdue opens and plan lead + overdue dispatches."""
    solo = settings or AppSettings.get_solo()
    result = PlanResult()
    result.cancelled = cancel_open_dispatches(
        item=item,
        kinds=(
            SystemEnums.ReminderKind.DUE_APPROACHING,
            SystemEnums.ReminderKind.OVERDUE,
        ),
    )

    if not item.due_at or not item_eligible_for_reminders(item, solo):
        result.skipped += 1
        return result

    channel = "webhook_ntfy"
    from lifeos_app.services.notify import dispatch_channel_name

    channel = dispatch_channel_name(solo.notification_channel)
    now = timezone.now()
    due = item.due_at

    for lead in lead_minutes_list(solo):
        fire_at = due - timedelta(minutes=lead)
        # Still useful if already inside the lead window — fire ASAP.
        if fire_at < now - timedelta(minutes=1):
            fire_at = now
        row, created = _upsert_dispatch(
            item=item,
            kind=SystemEnums.ReminderKind.DUE_APPROACHING,
            fire_at=fire_at,
            lead_minutes=lead,
            channel=channel,
        )
        if created and row:
            result.created += 1
            if enqueue_eta and _enqueue_eta(row):
                result.enqueued += 1
        elif not created:
            result.skipped += 1

    # Overdue: one per calendar day bucket at due_at (or now if already past).
    overdue_fire = due if due > now else now
    row, created = _upsert_dispatch(
        item=item,
        kind=SystemEnums.ReminderKind.OVERDUE,
        fire_at=overdue_fire,
        lead_minutes=0,
        channel=channel,
    )
    if created and row:
        result.created += 1
        if enqueue_eta and _enqueue_eta(row):
            result.enqueued += 1

    return result


def plan_allocation_reminders(
    allocation: ScheduledAllocation,
    *,
    settings: AppSettings | None = None,
    enqueue_eta: bool = True,
) -> PlanResult:
    """Cancel prior allocation-start opens and plan lead dispatches."""
    solo = settings or AppSettings.get_solo()
    item = allocation.execution_item
    result = PlanResult()
    result.cancelled = cancel_open_dispatches(
        allocation=allocation,
        kinds=(SystemEnums.ReminderKind.ALLOCATION_START,),
    )

    if not item_eligible_for_reminders(item, solo):
        result.skipped += 1
        return result

    from lifeos_app.services.notify import dispatch_channel_name

    channel = dispatch_channel_name(solo.notification_channel)
    now = timezone.now()
    start = allocation.start_at

    for lead in lead_minutes_list(solo):
        fire_at = start - timedelta(minutes=lead)
        if fire_at < now - timedelta(minutes=1):
            fire_at = now
        row, created = _upsert_dispatch(
            item=item,
            kind=SystemEnums.ReminderKind.ALLOCATION_START,
            fire_at=fire_at,
            lead_minutes=lead,
            allocation=allocation,
            channel=channel,
        )
        if created and row:
            result.created += 1
            if enqueue_eta and _enqueue_eta(row):
                result.enqueued += 1
        elif not created:
            result.skipped += 1

    return result


def rearm_due_reminders(item: ExecutionItem, **kwargs) -> PlanResult:
    """Public alias — due_at create/update hook."""
    return plan_due_reminders(item, **kwargs)


def rearm_allocation_reminders(allocation: ScheduledAllocation, **kwargs) -> PlanResult:
    """Public alias — allocation create/update hook."""
    return plan_allocation_reminders(allocation, **kwargs)


def plan_safety_net(*, horizon_hours: int = 48) -> PlanResult:
    """Beat/sweep helper — ensure upcoming dues/allocations have PENDING rows."""
    solo = AppSettings.get_solo()
    now = timezone.now()
    horizon = now + timedelta(hours=horizon_hours)
    result = PlanResult()

    items = ExecutionItem.objects.filter(
        is_deleted=False,
        due_at__isnull=False,
        due_at__lte=horizon + timedelta(minutes=max(lead_minutes_list(solo) or [15])),
    ).exclude(status=SystemEnums.ItemStatus.COMPLETED)
    for item in items.iterator():
        if not item_eligible_for_reminders(item, solo):
            continue
        # Skip if an open due-approaching already exists for this item.
        has_open = ReminderDispatch.objects.filter(
            execution_item=item,
            kind=SystemEnums.ReminderKind.DUE_APPROACHING,
            status__in=_OPEN_DISPATCH,
        ).exists()
        if has_open:
            result.skipped += 1
            continue
        sub = plan_due_reminders(item, settings=solo, enqueue_eta=True)
        result.created += sub.created
        result.enqueued += sub.enqueued
        result.cancelled += sub.cancelled

    allocs = ScheduledAllocation.objects.filter(
        start_at__gte=now - timedelta(minutes=5),
        start_at__lte=horizon + timedelta(minutes=max(lead_minutes_list(solo) or [15])),
    ).select_related("execution_item")
    for alloc in allocs.iterator():
        has_open = ReminderDispatch.objects.filter(
            scheduled_allocation=alloc,
            kind=SystemEnums.ReminderKind.ALLOCATION_START,
            status__in=_OPEN_DISPATCH,
        ).exists()
        if has_open:
            result.skipped += 1
            continue
        sub = plan_allocation_reminders(alloc, settings=solo, enqueue_eta=True)
        result.created += sub.created
        result.enqueued += sub.enqueued
        result.cancelled += sub.cancelled

    return result


def in_quiet_hours(settings: AppSettings | None = None, *, now: datetime | None = None) -> bool:
    """True when current local time falls inside configured quiet hours."""
    solo = settings or AppSettings.get_solo()
    start = solo.quiet_hours_start
    end = solo.quiet_hours_end
    if not start or not end:
        return False
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(solo.timezone or "UTC")
    except Exception:
        tz = timezone.get_current_timezone()
    local_now = (now or timezone.now()).astimezone(tz)
    t = local_now.time()
    if start <= end:
        return start <= t < end
    # Wraps midnight
    return t >= start or t < end


def fire_single_dispatch(dispatch_id: int) -> dict:
    """Deliver one PENDING dispatch if due (Celery ETA target)."""
    from lifeos_app.services.notify import (
        ReminderPayload,
        deliver_webhook,
        dispatch_channel_name,
    )

    try:
        dispatch = ReminderDispatch.objects.select_related("execution_item").get(pk=dispatch_id)
    except ReminderDispatch.DoesNotExist:
        return {"ok": False, "reason": "missing"}

    if dispatch.status != SystemEnums.ReminderDispatchStatus.PENDING:
        return {"ok": False, "reason": f"status={dispatch.status}"}
    now = timezone.now()
    if dispatch.snooze_until and dispatch.snooze_until > now:
        return {"ok": False, "reason": "snoozed"}
    if dispatch.fire_at > now:
        return {"ok": False, "reason": "not_due"}

    settings = AppSettings.get_solo()
    if in_quiet_hours(settings, now=now):
        return {"ok": False, "reason": "quiet_hours"}
    if not settings.notifications_enabled:
        dispatch.status = SystemEnums.ReminderDispatchStatus.FAILED
        dispatch.last_error = "notifications_disabled"
        dispatch.save(update_fields=["status", "last_error", "updated_at"])
        return {"ok": False, "reason": "notifications_disabled"}
    if not settings.notification_webhook_url:
        dispatch.status = SystemEnums.ReminderDispatchStatus.FAILED
        dispatch.last_error = "webhook_not_configured"
        dispatch.save(update_fields=["status", "last_error", "updated_at"])
        return {"ok": False, "reason": "webhook_not_configured"}

    payload = ReminderPayload(
        title=dispatch.execution_item.title,
        kind=dispatch.kind,
        item_id=dispatch.execution_item_id,
        dedupe_key=dispatch.dedupe_key,
        fire_at=dispatch.fire_at.isoformat(),
    )
    try:
        deliver_webhook(
            channel=settings.notification_channel,
            url=settings.notification_webhook_url,
            token=settings.notification_webhook_token,
            payload=payload,
        )
        dispatch.status = SystemEnums.ReminderDispatchStatus.SENT
        dispatch.sent_at = now
        dispatch.channel = dispatch_channel_name(settings.notification_channel)
        dispatch.last_error = ""
        dispatch.save(
            update_fields=["status", "sent_at", "channel", "last_error", "updated_at"]
        )
        return {"ok": True, "sent": 1}
    except Exception as exc:  # noqa: BLE001
        dispatch.status = SystemEnums.ReminderDispatchStatus.FAILED
        dispatch.last_error = str(exc)[:500]
        dispatch.save(update_fields=["status", "last_error", "updated_at"])
        return {"ok": False, "reason": str(exc)[:200]}
