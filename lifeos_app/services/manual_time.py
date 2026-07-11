# ==============================================================================
# File: lifeos_app/services/manual_time.py
# Description: Manual time add for items and containers (BL-TIME-004 / FR-FOCUS-002)
# Component: Services / Focus
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Increment ``extra_actual_seconds`` without fabricating FocusSession rows."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from lifeos_app.models import ExecutionItem, WorkspaceContainer
from lifeos_app.services.time_format import format_duration_seconds, parse_duration_minutes


@dataclass
class ManualTimeResult:
    """Outcome of a manual time add."""

    ok: bool
    message: str = ""
    added_seconds: int = 0


@dataclass
class SpentBreakdown:
    """Display totals for drawer time sections."""

    timer_seconds: int = 0
    manual_seconds: int = 0
    own_extra_seconds: int = 0
    total_seconds: int = 0

    @property
    def timer_label(self) -> str:
        return format_duration_seconds(self.timer_seconds)

    @property
    def manual_label(self) -> str:
        return format_duration_seconds(self.manual_seconds)

    @property
    def own_extra_label(self) -> str:
        return format_duration_seconds(self.own_extra_seconds)

    @property
    def total_label(self) -> str:
        return format_duration_seconds(self.total_seconds)


def _parse_duration_to_seconds(raw: str) -> int | None:
    """Accept human durations (``1h``, ``45m``) or bare minutes."""
    minutes = parse_duration_minutes(raw)
    if minutes is None or minutes <= 0:
        return None
    return int(minutes) * 60


def item_spent_breakdown(item: ExecutionItem) -> SpentBreakdown:
    """Timer + manual extras for a leaf."""
    timer = int(item.time_spent_seconds or 0)
    manual = int(item.extra_actual_seconds or 0)
    return SpentBreakdown(
        timer_seconds=timer,
        manual_seconds=manual,
        own_extra_seconds=0,
        total_seconds=timer + manual,
    )


def _descendant_item_seconds(container: WorkspaceContainer) -> tuple[int, int]:
    """Sum timer/manual seconds for items under this container (recursive)."""
    timer = 0
    manual = 0
    for item in container.execution_items.filter(is_deleted=False).only(
        "time_spent_seconds", "extra_actual_seconds"
    ):
        timer += int(item.time_spent_seconds or 0)
        manual += int(item.extra_actual_seconds or 0)
    for child in container.children.all():
        t, m = _descendant_item_seconds(child)
        timer += t
        manual += m
    return timer, manual


def container_spent_breakdown(container: WorkspaceContainer) -> SpentBreakdown:
    """Descendant item time + container-level manual extras (FR-FOCUS-003)."""
    timer, manual = _descendant_item_seconds(container)
    own = int(container.extra_actual_seconds or 0)
    return SpentBreakdown(
        timer_seconds=timer,
        manual_seconds=manual,
        own_extra_seconds=own,
        total_seconds=timer + manual + own,
    )


def _append_note(existing: str, duration_label: str, note: str) -> str:
    stamp = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    line = f"[{stamp}] +{duration_label}"
    if note.strip():
        line = f"{line} — {note.strip()}"
    existing = (existing or "").rstrip()
    if existing:
        return f"{existing}\n{line}"
    return line


@transaction.atomic
def add_time_to_item(item: ExecutionItem, duration_text: str, note: str = "") -> ManualTimeResult:
    """Add manual seconds to an execution item."""
    seconds = _parse_duration_to_seconds(duration_text)
    if seconds is None:
        return ManualTimeResult(ok=False, message="Enter a duration like 45m or 1h 30m.")

    item.extra_actual_seconds = int(item.extra_actual_seconds or 0) + seconds
    item.notes = _append_note(
        item.notes,
        format_duration_seconds(seconds),
        note,
    )
    item.save(update_fields=["extra_actual_seconds", "notes", "updated_at"])
    return ManualTimeResult(
        ok=True,
        message=f"Added {format_duration_seconds(seconds)} manual time.",
        added_seconds=seconds,
    )


@transaction.atomic
def add_time_to_container(
    container: WorkspaceContainer, duration_text: str, note: str = ""
) -> ManualTimeResult:
    """Add manual seconds on a container (not rolled into leaf sessions)."""
    seconds = _parse_duration_to_seconds(duration_text)
    if seconds is None:
        return ManualTimeResult(ok=False, message="Enter a duration like 45m or 1h 30m.")

    container.extra_actual_seconds = int(container.extra_actual_seconds or 0) + seconds
    container.notes = _append_note(
        container.notes,
        format_duration_seconds(seconds),
        note,
    )
    container.save(update_fields=["extra_actual_seconds", "notes", "updated_at"])
    msg = f"Added {format_duration_seconds(seconds)} to container."
    if note.strip():
        msg = f"{msg} Noted."
    return ManualTimeResult(ok=True, message=msg, added_seconds=seconds)
