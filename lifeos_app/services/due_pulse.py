# ==============================================================================
# File: lifeos_app/services/due_pulse.py
# Description: Ambient due-soon / overdue classification for row pulse (FR-UI-028)
# Component: Services / Notifications polish
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Classify leaf due urgency for calm in-app pulse styling.

Status accent bars stay static; this only drives ``data-due`` wash animation
on Matrix / Overview / Board (and Horizon) rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from lifeos_app.models import AppSettings, SystemEnums

# Template / CSS token values — keep in sync with themes.css selectors.
DUE_NONE = ""
DUE_SOON = "soon"
DUE_OVERDUE = "overdue"

_TERMINAL_STATUSES = frozenset({SystemEnums.ItemStatus.COMPLETED})


def soon_window_minutes(settings: AppSettings | None = None) -> int:
    """Minutes ahead of ``due_at`` that count as due-soon for ambient pulse.

    Uses the wider of primary and secondary reminder leads so Matrix scanning
    sees items due within the day (default second lead = 1440), not only the
    last 15 minutes.
    """
    solo = settings or AppSettings.get_solo()
    leads = [int(solo.reminder_lead_minutes or 15)]
    second = solo.reminder_second_lead_minutes
    if second is not None:
        leads.append(int(second))
    return max(leads)


def classify_due_urgency(
    item: Any,
    *,
    now: datetime | None = None,
    settings: AppSettings | None = None,
    soon_minutes: int | None = None,
) -> str:
    """Return ``overdue``, ``soon``, or ``\"\"`` for an execution item.

    Completed items never pulse. Missing ``due_at`` never pulses.
    """
    status = getattr(item, "status", None)
    if status in _TERMINAL_STATUSES:
        return DUE_NONE

    due_at = getattr(item, "due_at", None)
    if due_at is None:
        return DUE_NONE

    clock = now or timezone.now()
    if timezone.is_naive(due_at):
        due_at = timezone.make_aware(due_at, timezone.get_current_timezone())

    if due_at < clock:
        return DUE_OVERDUE

    window = soon_minutes if soon_minutes is not None else soon_window_minutes(settings)
    if due_at <= clock + timedelta(minutes=window):
        return DUE_SOON

    return DUE_NONE
