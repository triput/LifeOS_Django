# ==============================================================================
# File: lifeos_app/services/focus.py
# Description: Server-authoritative Focus Engine (ENG-FOCUS)
# Component: Services / Focus Engine
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Focus session lifecycle — start, pause, complete with server truth."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from lifeos_app.models import ExecutionItem, FocusSession, SystemEnums
from lifeos_app.services.recurrence import advance_recurrence_on_complete


@dataclass
class FocusResult:
    """Outcome of a focus mutation."""

    ok: bool
    message: str = ""
    session: FocusSession | None = None
    item: ExecutionItem | None = None


def _elapsed_seconds(session: FocusSession, now=None) -> int:
    now = now or timezone.now()
    return max(0, int((now - session.started_at).total_seconds()))


def _close_session(session: FocusSession, reason: str, now=None) -> FocusSession:
    """Close an open session and accumulate elapsed time on the item."""
    now = now or timezone.now()
    if session.ended_at is not None:
        return session
    elapsed = _elapsed_seconds(session, now)
    session.ended_at = now
    session.duration_seconds = elapsed
    session.end_reason = reason
    session.save(update_fields=["ended_at", "duration_seconds", "end_reason"])
    item = session.execution_item
    item.time_spent_seconds += elapsed
    item.save(update_fields=["time_spent_seconds", "updated_at"])
    return session


def get_open_session() -> FocusSession | None:
    return (
        FocusSession.objects.filter(ended_at__isnull=True)
        .select_related("execution_item")
        .first()
    )


@transaction.atomic
def start_focus(item: ExecutionItem) -> FocusResult:
    """Start focus on an item, preempting any open session."""
    if item.is_deleted:
        return FocusResult(ok=False, message="Item is deleted.")
    if item.status == SystemEnums.ItemStatus.COMPLETED:
        return FocusResult(ok=False, message="Item is already completed.")

    now = timezone.now()
    open_sess = get_open_session()
    if open_sess:
        if open_sess.execution_item_id == item.pk:
            return FocusResult(ok=True, message="Already in focus.", session=open_sess, item=item)
        _close_session(open_sess, SystemEnums.FocusEndReason.PREEMPTED, now)

    session = FocusSession.objects.create(execution_item=item, started_at=now)
    if item.status != SystemEnums.ItemStatus.IN_PROGRESS:
        item.status = SystemEnums.ItemStatus.IN_PROGRESS
        item.save(update_fields=["status", "updated_at"])
    return FocusResult(ok=True, message="Focus started.", session=session, item=item)


@transaction.atomic
def pause_focus() -> FocusResult:
    """Pause the active focus session."""
    open_sess = get_open_session()
    if not open_sess:
        return FocusResult(ok=False, message="No active focus session.")
    _close_session(open_sess, SystemEnums.FocusEndReason.PAUSE)
    return FocusResult(
        ok=True,
        message="Focus paused.",
        session=open_sess,
        item=open_sess.execution_item,
    )


@transaction.atomic
def complete_focus(item: ExecutionItem | None = None) -> FocusResult:
    """Complete focus — stop timer and mark item COMPLETED (spawn next if recurring)."""
    open_sess = get_open_session()
    if item is None and open_sess:
        item = open_sess.execution_item
    if item is None:
        return FocusResult(ok=False, message="No item to complete.")

    if item.has_unmet_dependencies:
        return FocusResult(
            ok=False,
            message="Cannot complete — waiting on unfinished prerequisites.",
            item=item,
        )

    now = timezone.now()
    if open_sess and open_sess.execution_item_id == item.pk:
        _close_session(open_sess, SystemEnums.FocusEndReason.COMPLETE, now)
    elif open_sess:
        _close_session(open_sess, SystemEnums.FocusEndReason.PREEMPTED, now)

    item.status = SystemEnums.ItemStatus.COMPLETED
    item.save(update_fields=["status", "updated_at"])

    from lifeos_app.services.reminders import cancel_open_dispatches

    cancel_open_dispatches(item=item)

    message = "Completed."
    nxt = advance_recurrence_on_complete(item)
    if nxt and nxt.due_at:
        message = f"Completed. Next occurrence due {nxt.due_at:%a %Y-%m-%d %H:%M}."
    elif nxt:
        message = "Completed. Next occurrence created."

    return FocusResult(ok=True, message=message, item=item)


def focus_elapsed_display(session: FocusSession | None) -> str:
    """Human-readable HH:MM:SS from server timestamps."""
    if not session or session.ended_at:
        return "00:00:00"
    total = _elapsed_seconds(session)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
