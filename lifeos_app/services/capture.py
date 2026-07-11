# ==============================================================================
# File: lifeos_app/services/capture.py
# Description: Deterministic Lightning Capture parser (ENG-CMD Tier 1)
# Component: Services / Command Engine
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Token-based capture parser for Cmd+K Lightning Capture."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from lifeos_app.models import SystemEnums, WorkspaceContainer
from lifeos_app.services.recurrence import RecurrencePreview, extract_recurrence
from lifeos_app.services.time_format import parse_duration_minutes

try:
    import dateparser
except ImportError:  # pragma: no cover - optional until requirements install
    dateparser = None  # type: ignore[assignment]

# Order-independent token patterns
CONTAINER_RE = re.compile(r"^#([\w-]+)$", re.IGNORECASE)
TAG_RE = re.compile(r"^@([\w-]+)$", re.IGNORECASE)
PRIORITY_RE = re.compile(r"^p([1-4])$", re.IGNORECASE)
URGENCY_MAP = {
    "!urgent": SystemEnums.UrgencyLevel.HIGH,
    "!immediate": SystemEnums.UrgencyLevel.IMMEDIATE,
    "urgent": SystemEnums.UrgencyLevel.HIGH,
    "immediate": SystemEnums.UrgencyLevel.IMMEDIATE,
}
FUZZY_MAP = {
    "today": SystemEnums.FuzzyTimeframe.TODAY,
    "tomorrow": SystemEnums.FuzzyTimeframe.TOMORROW,
    "weekend": SystemEnums.FuzzyTimeframe.WEEKEND,
    "this-week": SystemEnums.FuzzyTimeframe.THIS_WEEK,
    "this_week": SystemEnums.FuzzyTimeframe.THIS_WEEK,
    "this-month": SystemEnums.FuzzyTimeframe.THIS_MONTH,
    "this_month": SystemEnums.FuzzyTimeframe.THIS_MONTH,
}
CHRONO_PREFIXES = ("due", "by", "at", "on")
ESTIMATE_PREFIXES = ("for", "est", "estimate")


@dataclass
class CapturePreview:
    """Structured preview of a capture-mode parse."""

    raw: str
    title: str = ""
    container_slug: str | None = None
    container_title: str | None = None
    container_found: bool = False
    tag_slugs: list[str] = field(default_factory=list)
    priority: int | None = None
    urgency: str | None = None
    due_at: datetime | None = None
    estimated_minutes: int | None = None
    fuzzy_timeframe: str = SystemEnums.FuzzyTimeframe.NONE
    status: str = SystemEnums.ItemStatus.INBOX
    recurrence: RecurrencePreview | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "title": self.title,
            "container_slug": self.container_slug,
            "container_title": self.container_title,
            "container_found": self.container_found,
            "tag_slugs": self.tag_slugs,
            "priority": self.priority,
            "urgency": self.urgency,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "estimated_minutes": self.estimated_minutes,
            "fuzzy_timeframe": self.fuzzy_timeframe,
            "status": self.status,
            "recurrence": self.recurrence.as_dict() if self.recurrence else None,
            "warnings": self.warnings,
        }


def _parse_chrono_phrase(phrase: str, tz_name: str) -> datetime | None:
    """Parse a chrono phrase with dateparser when available."""
    if not phrase.strip():
        return None
    if dateparser is None:
        return None
    parsed = dateparser.parse(
        phrase,
        settings={
            "TIMEZONE": tz_name,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        },
    )
    return parsed


def parse_capture(raw: str, tz_name: str = "UTC") -> CapturePreview:
    """Parse free-text capture input into structured preview fields."""
    preview = CapturePreview(raw=raw.strip())
    if not preview.raw:
        preview.warnings.append("Enter a title or tokens to capture.")
        return preview

    # FR-CMD-005 — strip recurrence phrase before tokenizing title/tokens.
    working, recurrence = extract_recurrence(preview.raw, tz_name=tz_name)
    preview.recurrence = recurrence
    if recurrence:
        if recurrence.ambiguous and recurrence.warning:
            preview.warnings.append(recurrence.warning)
        elif recurrence.next_occurrence_at and preview.due_at is None:
            preview.due_at = recurrence.next_occurrence_at

    if not working.strip():
        preview.warnings.append("Enter a title or tokens to capture.")
        return preview

    tokens = working.split()
    title_parts: list[str] = []
    chrono_parts: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        lower = tok.lower()

        m = CONTAINER_RE.match(tok)
        if m:
            slug = m.group(1).lower()
            preview.container_slug = slug
            container = WorkspaceContainer.objects.filter(slug=slug).first()
            if container:
                preview.container_found = True
                preview.container_title = container.title
            else:
                preview.warnings.append(f"Unknown container #{slug} — will land in Inbox.")
            i += 1
            continue

        m = TAG_RE.match(tok)
        if m:
            preview.tag_slugs.append(m.group(1).lower())
            i += 1
            continue

        m = PRIORITY_RE.match(tok)
        if m:
            preview.priority = int(m.group(1))
            i += 1
            continue

        if lower in URGENCY_MAP:
            preview.urgency = URGENCY_MAP[lower]
            i += 1
            continue

        if lower in FUZZY_MAP:
            preview.fuzzy_timeframe = FUZZY_MAP[lower]
            i += 1
            continue

        # Estimate: ~2h · for 90m · est 1h
        if tok.startswith("~"):
            mins = parse_duration_minutes(tok[1:])
            if mins:
                preview.estimated_minutes = mins
                i += 1
                continue

        if lower in ESTIMATE_PREFIXES and i + 1 < len(tokens):
            mins = parse_duration_minutes(tokens[i + 1])
            if mins:
                preview.estimated_minutes = mins
                i += 2
                continue

        if lower in CHRONO_PREFIXES and i + 1 < len(tokens):
            # Bare "at 9am" without "every" is one-shot chrono; recurrence already stripped.
            chrono_parts.append(" ".join(tokens[i:]))
            break

        if lower in ("due", "by") and i + 1 < len(tokens):
            chrono_parts.append(" ".join(tokens[i + 1 :]))
            break

        # Inline chrono heuristics: "tomorrow", "next friday", "3pm"
        if dateparser is not None:
            trial = _parse_chrono_phrase(tok, tz_name)
            if trial and trial > timezone.now() - timedelta(hours=12):
                preview.due_at = trial
                i += 1
                continue
            if i + 1 < len(tokens):
                pair = f"{tok} {tokens[i + 1]}"
                trial_pair = _parse_chrono_phrase(pair, tz_name)
                if trial_pair:
                    preview.due_at = trial_pair
                    i += 2
                    continue

        title_parts.append(tok)
        i += 1

    if chrono_parts and preview.due_at is None:
        phrase = chrono_parts[0]
        if phrase.lower().startswith("due "):
            phrase = phrase[4:]
        parsed = _parse_chrono_phrase(phrase, tz_name)
        if parsed:
            preview.due_at = parsed
        else:
            preview.warnings.append(f"Could not parse date: {phrase!r}")

    preview.title = " ".join(title_parts).strip()

    if not preview.title:
        preview.title = working.strip() or preview.raw
        preview.warnings.append("No title tokens found — using full input as title.")

    if preview.container_found:
        preview.status = SystemEnums.ItemStatus.BACKLOG
    else:
        preview.status = SystemEnums.ItemStatus.INBOX

    if preview.due_at and preview.status == SystemEnums.ItemStatus.BACKLOG:
        preview.status = SystemEnums.ItemStatus.PLANNED

    # Recurrence due wins when no explicit one-shot due was set later.
    if (
        preview.recurrence
        and not preview.recurrence.ambiguous
        and preview.recurrence.next_occurrence_at
        and preview.due_at is None
    ):
        preview.due_at = preview.recurrence.next_occurrence_at
        if preview.status == SystemEnums.ItemStatus.BACKLOG:
            preview.status = SystemEnums.ItemStatus.PLANNED

    return preview
