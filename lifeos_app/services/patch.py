# ==============================================================================
# File: lifeos_app/services/patch.py
# Description: Inline field mutation for Matrix cells and detail drawers
# Component: Services / Patch
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Authoritative patch-field logic for items and containers (FR-UI-001, FR-UI-003)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from lifeos_app.models import ExecutionItem, SystemEnums, WorkspaceContainer
from lifeos_app.services.time_format import format_duration_minutes, parse_duration_minutes

ITEM_EDITABLE = {
    "title",
    "status",
    "priority",
    "urgency",
    "estimated_minutes",
    "notes",
    "due_at",
    "external_url",
}
CONTAINER_EDITABLE = {
    "title",
    "para_state",
    "priority",
    "urgency",
    "provider",
    "credits_earned",
    "credit_unit_type",
    "external_url",
    "notes",
}


@dataclass
class PatchResult:
    ok: bool
    message: str = ""
    field: str = ""
    value: str = ""


def _parse_due_at(value: str):
    """Parse datetime-local / ISO string into aware datetime, or None if cleared."""
    raw = (value or "").strip()
    if not raw:
        return None
    # datetime-local posts "YYYY-MM-DDTHH:MM" (no seconds / tz)
    if len(raw) == 16 and "T" in raw:
        raw = raw + ":00"
    parsed = parse_datetime(raw)
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("Invalid due date.") from exc
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def patch_item_field(item: ExecutionItem, field: str, value: str) -> PatchResult:
    """Apply a single-field update to an execution item."""
    if field not in ITEM_EDITABLE:
        return PatchResult(ok=False, message=f"Field {field!r} is not editable.")

    if field == "status":
        new_status = value.strip().upper()
        valid = {c[0] for c in SystemEnums.ItemStatus.choices}
        if new_status not in valid:
            return PatchResult(ok=False, message="Invalid status.")
        if new_status == SystemEnums.ItemStatus.COMPLETED and item.has_unmet_dependencies:
            return PatchResult(ok=False, message="Cannot complete — waiting on prerequisites.")
        if new_status in (SystemEnums.ItemStatus.IN_PROGRESS, SystemEnums.ItemStatus.COMPLETED):
            if item.has_unmet_dependencies:
                return PatchResult(ok=False, message="Blocked by unfinished dependencies.")
        was_completed = item.status == SystemEnums.ItemStatus.COMPLETED
        item.status = new_status
        item.save(update_fields=["status", "updated_at"])
        if (
            new_status == SystemEnums.ItemStatus.COMPLETED
            and not was_completed
        ):
            from lifeos_app.services.recurrence import advance_recurrence_on_complete
            from lifeos_app.services.reminders import cancel_open_dispatches

            cancel_open_dispatches(item=item)
            nxt = advance_recurrence_on_complete(item)
            if nxt and nxt.due_at:
                from lifeos_app.services.reminders import rearm_due_reminders

                rearm_due_reminders(nxt)
                return PatchResult(
                    ok=True,
                    field=field,
                    value=new_status,
                    message=f"Completed. Next due {nxt.due_at:%a %Y-%m-%d %H:%M}.",
                )
        return PatchResult(ok=True, field=field, value=new_status)

    if field == "priority":
        try:
            pri = int(value)
        except ValueError:
            return PatchResult(ok=False, message="Priority must be 1–4.")
        if pri not in dict(SystemEnums.PriorityLevel.choices):
            return PatchResult(ok=False, message="Priority must be 1–4.")
        item.priority = pri
        item.save(update_fields=["priority", "updated_at"])
        return PatchResult(ok=True, field=field, value=str(pri))

    if field == "urgency":
        val = value.strip().upper()
        if val not in dict(SystemEnums.UrgencyLevel.choices):
            return PatchResult(ok=False, message="Invalid urgency.")
        item.urgency = val
        item.save(update_fields=["urgency", "updated_at"])
        return PatchResult(ok=True, field=field, value=val)

    if field == "estimated_minutes":
        mins = parse_duration_minutes(value)
        if mins is None:
            return PatchResult(
                ok=False,
                message="Use a duration like 90, 90m, or 1h 30m.",
            )
        mins = max(1, mins)
        item.estimated_minutes = mins
        item.save(update_fields=["estimated_minutes", "updated_at"])
        return PatchResult(
            ok=True,
            field=field,
            value=format_duration_minutes(mins),
            message=f"Estimate {format_duration_minutes(mins)}.",
        )

    if field == "due_at":
        try:
            item.due_at = _parse_due_at(value)
        except ValueError as exc:
            return PatchResult(ok=False, message=str(exc))
        item.save(update_fields=["due_at", "updated_at"])
        from lifeos_app.services.reminders import rearm_due_reminders

        rearm_due_reminders(item)
        return PatchResult(ok=True, field=field, value=value)

    if field == "external_url":
        item.external_url = value.strip()[:2000]
        item.save(update_fields=["external_url", "updated_at"])
        return PatchResult(ok=True, field=field, value=item.external_url)

    # title, notes — plain text
    setattr(item, field, value.strip()[:255] if field == "title" else value.strip())
    item.save(update_fields=[field, "updated_at"])
    return PatchResult(ok=True, field=field, value=value)


def patch_container_field(container: WorkspaceContainer, field: str, value: str) -> PatchResult:
    """Apply a single-field update to a workspace container."""
    if field not in CONTAINER_EDITABLE:
        return PatchResult(ok=False, message=f"Field {field!r} is not editable.")

    if field == "para_state":
        val = value.strip().upper()
        if val not in dict(SystemEnums.PARACategory.choices):
            return PatchResult(ok=False, message="Invalid PARA state.")
        container.para_state = val
        container.is_archived = val == SystemEnums.PARACategory.ARCHIVE
        container.save(update_fields=["para_state", "is_archived", "updated_at"])
        return PatchResult(ok=True, field=field, value=val)

    if field == "priority":
        try:
            pri = int(value)
        except ValueError:
            return PatchResult(ok=False, message="Priority must be 1–4.")
        container.priority = pri
        container.save(update_fields=["priority", "updated_at"])
        return PatchResult(ok=True, field=field, value=str(pri))

    if field == "urgency":
        val = value.strip().upper()
        if val not in dict(SystemEnums.UrgencyLevel.choices):
            return PatchResult(ok=False, message="Invalid urgency.")
        container.urgency = val
        container.save(update_fields=["urgency", "updated_at"])
        return PatchResult(ok=True, field=field, value=val)

    if field == "credits_earned":
        try:
            credits = float(value) if str(value).strip() else 0.0
        except ValueError:
            return PatchResult(ok=False, message="Credits must be a number.")
        container.credits_earned = max(0.0, credits)
        container.save(update_fields=["credits_earned", "updated_at"])
        return PatchResult(ok=True, field=field, value=str(container.credits_earned))

    if field in ("provider", "credit_unit_type", "external_url", "notes"):
        if field == "notes":
            container.notes = value.strip()
            container.save(update_fields=["notes", "updated_at"])
            return PatchResult(ok=True, field=field, value=container.notes)
        maxlen = 2000 if field == "external_url" else 100 if field == "provider" else 32
        setattr(container, field, value.strip()[:maxlen])
        container.save(update_fields=[field, "updated_at"])
        return PatchResult(ok=True, field=field, value=getattr(container, field))

    container.title = value.strip()[:255]
    try:
        container.full_clean()
        container.save(update_fields=["title", "updated_at"])
    except ValidationError as exc:
        msg = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        return PatchResult(ok=False, message=msg)
    return PatchResult(ok=True, field=field, value=container.title)


def bulk_update_items(item_ids: list[int], action: str, value: str = "") -> PatchResult:
    """Bulk status update for selected matrix rows."""
    items = list(ExecutionItem.objects.filter(pk__in=item_ids, is_deleted=False))
    if not items:
        return PatchResult(ok=False, message="No items selected.")

    if action == "status":
        updated = 0
        errors = []
        for item in items:
            result = patch_item_field(item, "status", value)
            if result.ok:
                updated += 1
            else:
                errors.append(f"{item.title}: {result.message}")
        if errors:
            return PatchResult(ok=False, message=f"Updated {updated}. " + "; ".join(errors[:3]))
        return PatchResult(ok=True, message=f"Updated {updated} items.", value=value)

    if action == "soft_delete":
        count = ExecutionItem.objects.filter(pk__in=item_ids).update(is_deleted=True)
        return PatchResult(ok=True, message=f"Archived {count} items.")

    return PatchResult(ok=False, message=f"Unknown bulk action: {action}")
