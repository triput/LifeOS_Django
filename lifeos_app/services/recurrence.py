# ==============================================================================
# File: lifeos_app/services/recurrence.py
# Description: NL recurrence parse + advance-on-complete (FR-CMD-005 / FR-DATA-010)
# Component: Services / Recurrence
# Version: 1.2 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Deterministic recurrence phrases for Lightning Capture and completion spawn.

On complete of an active recurring item: leave the completed row as history and
spawn the next occurrence (rule moves to the new leaf).

BL-REC-001: optional ``starting <date>`` floors the first occurrence.
BL-REC-002: optional ``ending`` / ``until <date>`` stops spawn past that day.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from lifeos_app.models import (
    ExecutionItem,
    ItemContainerLink,
    RecurrenceRule,
    SystemEnums,
)

try:
    import dateparser
except ImportError:  # pragma: no cover
    dateparser = None  # type: ignore[assignment]

_WEEKDAY_ALIASES = {
    "mon": "MO",
    "monday": "MO",
    "mo": "MO",
    "tue": "TU",
    "tues": "TU",
    "tuesday": "TU",
    "tu": "TU",
    "wed": "WE",
    "weds": "WE",
    "wednesday": "WE",
    "we": "WE",
    "thu": "TH",
    "thur": "TH",
    "thurs": "TH",
    "thursday": "TH",
    "th": "TH",
    "fri": "FR",
    "friday": "FR",
    "fr": "FR",
    "sat": "SA",
    "saturday": "SA",
    "sa": "SA",
    "sun": "SU",
    "sunday": "SU",
    "su": "SU",
}

_ICAL_TO_PYTHON = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}

_AT_TIME_RE = re.compile(
    r"\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
    re.IGNORECASE,
)

# Optional series start (BL-REC-001). Stop before ending/until.
_STARTING_RE = re.compile(
    r",?\s*\bstarting(?:\s+on)?\s+(.+?)(?=,?\s*\bending\b|,?\s*\buntil\b|$)",
    re.IGNORECASE,
)

# Optional series end (BL-REC-002). ``until`` ≡ ``ending``.
_ENDING_RE = re.compile(
    r",?\s*\b(?:ending(?:\s+on)?|until)\s+(.+?)(?=,?\s*\bstarting\b|$)",
    re.IGNORECASE,
)

# Longest / most specific first.
_RECURRENCE_RES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\bevery\s+weekday(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?\b",
            re.IGNORECASE,
        ),
        "weekday",
    ),
    (
        re.compile(
            r"\bevery\s+day(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?\b",
            re.IGNORECASE,
        ),
        "day",
    ),
    (
        re.compile(
            r"\bevery\s+week(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?\b",
            re.IGNORECASE,
        ),
        "week",
    ),
    (
        re.compile(
            r"\bevery\s+month(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?\b",
            re.IGNORECASE,
        ),
        "month",
    ),
    (
        re.compile(
            r"\bevery\s+((?:mon|tue|wed|thu|fri|sat|sun)[a-z]*)"
            r"(?:\s*,\s*((?:mon|tue|wed|thu|fri|sat|sun)[a-z]*))*"
            r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?\b",
            re.IGNORECASE,
        ),
        "weekdays",
    ),
]

_AMBIGUOUS_RE = re.compile(
    r"\bevery\s+(?:other|few|\d+)(?:\s+\w+)?\b|\bevery\s+\w+\s+and\s+\w+\b",
    re.IGNORECASE,
)


@dataclass
class RecurrencePreview:
    """Parsed recurrence ready to attach on capture commit."""

    rrule_text: str
    freq: str
    byweekday: str = ""
    byhour: int | None = None
    byminute: int = 0
    interval: int = 1
    next_occurrence_at: datetime | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    ambiguous: bool = False
    warning: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "rrule_text": self.rrule_text,
            "freq": self.freq,
            "byweekday": self.byweekday,
            "byhour": self.byhour,
            "byminute": self.byminute,
            "interval": self.interval,
            "next_occurrence_at": (
                self.next_occurrence_at.isoformat() if self.next_occurrence_at else None
            ),
            "starts_at": self.starts_at.isoformat() if self.starts_at else None,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "ambiguous": self.ambiguous,
            "warning": self.warning,
        }


def _parse_at_time(matched: str) -> tuple[int | None, int]:
    """Return (hour_24, minute) from an 'at …' clause inside matched text."""
    m = _AT_TIME_RE.search(matched)
    if not m:
        return None, 0
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    ampm = (m.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    if not ampm and hour > 23:
        return None, 0
    if hour > 23 or minute > 59:
        return None, 0
    return hour, minute


def _normalize_weekdays(chunk: str) -> list[str]:
    parts = re.split(r"[\s,]+", chunk.strip())
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        key = part.lower().rstrip(".")
        code = _WEEKDAY_ALIASES.get(key)
        if code and code not in out:
            out.append(code)
    return out


def _aware(dt: datetime) -> datetime:
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _combine_local(day: datetime.date, hour: int, minute: int) -> datetime:
    return _aware(datetime.combine(day, time(hour=hour, minute=minute)))


def _occurrence_within_end(occurrence: datetime, ends_at: datetime | None) -> bool:
    """True when ``occurrence`` is on or before the series end day."""
    if ends_at is None:
        return True
    return occurrence.date() <= _aware(ends_at).date()


def _parse_bound_date(
    phrase: str, tz_name: str, *, label: str
) -> tuple[datetime | None, str]:
    """Parse a start/end date phrase with dateparser."""
    if not phrase:
        return None, f"Empty {label} date — ignored."
    if dateparser is None:
        return None, f"Could not parse {label} date {phrase!r} (dateparser missing)."
    parsed = dateparser.parse(
        phrase,
        settings={
            "TIMEZONE": tz_name or "UTC",
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
        },
    )
    if parsed is None:
        return None, f"Could not parse {label} date {phrase!r}."
    return _aware(parsed), ""


def _parse_starting_clause(
    text: str, tz_name: str
) -> tuple[str, datetime | None, str]:
    """Strip ``starting [on] <date>``; return (remainder, starts_at, warning)."""
    m = _STARTING_RE.search(text or "")
    if not m:
        return text, None, ""
    phrase = m.group(1).strip().rstrip(",.").strip()
    remainder = (text[: m.start()] + text[m.end() :]).strip()
    remainder = re.sub(r"\s{2,}", " ", remainder).strip(" ,.")
    remainder = re.sub(r"\s{2,}", " ", remainder).strip()
    bound, warning = _parse_bound_date(phrase, tz_name, label="starting")
    return remainder, bound, warning


def _parse_ending_clause(
    text: str, tz_name: str
) -> tuple[str, datetime | None, str]:
    """Strip ``ending [on] <date>`` / ``until <date>``; return (remainder, ends_at, warning)."""
    m = _ENDING_RE.search(text or "")
    if not m:
        return text, None, ""
    phrase = m.group(1).strip().rstrip(",.").strip()
    remainder = (text[: m.start()] + text[m.end() :]).strip()
    remainder = re.sub(r"\s{2,}", " ", remainder).strip(" ,.")
    remainder = re.sub(r"\s{2,}", " ", remainder).strip()
    bound, warning = _parse_bound_date(phrase, tz_name, label="ending")
    return remainder, bound, warning


def compute_next_occurrence(
    *,
    freq: str,
    byweekday: str = "",
    byhour: int | None = None,
    byminute: int = 0,
    interval: int = 1,
    after: datetime | None = None,
    not_before: datetime | None = None,
) -> datetime:
    """Next fire time strictly after ``after`` (default: now).

    When ``not_before`` is set (BL-REC-001), the first occurrence is the first
    matching slot on or after ``max(now/after, not_before)`` at the rule's time.
    """
    after = _aware(after or timezone.now())
    hour = 9 if byhour is None else int(byhour)
    minute = int(byminute or 0)
    interval = max(1, int(interval or 1))
    freq_u = (freq or "").upper()

    if not_before is not None:
        nb = _aware(not_before)
        # Date-only / midnight → apply rule wall-clock on that local day.
        if nb.hour == 0 and nb.minute == 0 and nb.second == 0 and nb.microsecond == 0:
            nb = _combine_local(nb.date(), hour, minute)
        floor = max(after, nb)
        # ``candidate > after`` — nudge so ``floor`` itself is eligible.
        after = floor - timedelta(microseconds=1)

    if freq_u == "DAILY":
        candidate = _combine_local(after.date(), hour, minute)
        if candidate <= after:
            candidate += timedelta(days=interval)
        while candidate <= after:
            candidate += timedelta(days=interval)
        return candidate

    if freq_u == "WEEKDAY":
        day = after.date()
        for _ in range(21):
            candidate = _combine_local(day, hour, minute)
            if candidate > after and day.weekday() < 5:
                return candidate
            day += timedelta(days=1)
        return _combine_local(after.date() + timedelta(days=1), hour, minute)

    if freq_u == "WEEKLY":
        codes = [c.strip().upper() for c in byweekday.split(",") if c.strip()]
        if not codes:
            candidate = after + timedelta(weeks=interval)
            return _combine_local(candidate.date(), hour, minute)
        wanted = {_ICAL_TO_PYTHON[c] for c in codes if c in _ICAL_TO_PYTHON}
        day = after.date()
        for _ in range(28):
            candidate = _combine_local(day, hour, minute)
            if candidate > after and day.weekday() in wanted:
                return candidate
            day += timedelta(days=1)
        return _combine_local(after.date() + timedelta(days=7), hour, minute)

    if freq_u == "MONTHLY":
        # Try the floor day first, then step months forward.
        day = after.date()
        target_day = min(day.day, 28)
        year, month = day.year, day.month
        for step in range(0, 14):
            y, m = year, month + step
            while m > 12:
                m -= 12
                y += 1
            last = calendar.monthrange(y, m)[1]
            candidate = _combine_local(
                datetime(y, m, min(target_day, last)).date(),
                hour,
                minute,
            )
            if candidate > after:
                return candidate
        return after + timedelta(days=30)

    return after + timedelta(days=1)


def extract_recurrence(raw: str, tz_name: str = "UTC") -> tuple[str, RecurrencePreview | None]:
    """Pull a recognized ``every …`` phrase out of capture text.

    Returns ``(remainder_without_phrase, preview_or_none)``. Ambiguous phrases
    yield a warning preview with ``ambiguous=True`` and are stripped so they do
    not pollute the title — commit stays non-recurring unless unambiguous.
    """
    text = raw or ""
    if not text.strip():
        return text, None

    # Bound clauses first so they do not pollute the title.
    text, starts_at, start_warning = _parse_starting_clause(text, tz_name)
    text, ends_at, end_warning = _parse_ending_clause(text, tz_name)
    bound_warning = " ".join(w for w in (start_warning, end_warning) if w).strip()

    if _AMBIGUOUS_RE.search(text) and not any(p.search(text) for p, _ in _RECURRENCE_RES):
        m = _AMBIGUOUS_RE.search(text)
        phrase = m.group(0) if m else "every …"
        remainder = (text[: m.start()] + text[m.end() :]).strip() if m else text
        remainder = re.sub(r"\s{2,}", " ", remainder).strip()
        return remainder, RecurrencePreview(
            rrule_text=phrase.strip(),
            freq="",
            ambiguous=True,
            warning=f"Ambiguous recurrence {phrase!r} — capture will be non-recurring.",
        )

    for pattern, kind in _RECURRENCE_RES:
        m = pattern.search(text)
        if not m:
            continue
        phrase = m.group(0).strip()
        remainder = (text[: m.start()] + text[m.end() :]).strip()
        remainder = re.sub(r"\s{2,}", " ", remainder).strip(" ,.")
        remainder = re.sub(r"\s{2,}", " ", remainder).strip()
        byhour, byminute = _parse_at_time(phrase)

        if kind == "day":
            preview = RecurrencePreview(
                rrule_text=phrase,
                freq="DAILY",
                byhour=byhour,
                byminute=byminute,
            )
        elif kind == "weekday":
            preview = RecurrencePreview(
                rrule_text=phrase,
                freq="WEEKDAY",
                byweekday="MO,TU,WE,TH,FR",
                byhour=byhour,
                byminute=byminute,
            )
        elif kind == "week":
            preview = RecurrencePreview(
                rrule_text=phrase,
                freq="WEEKLY",
                byweekday="",
                byhour=byhour,
                byminute=byminute,
            )
        elif kind == "month":
            preview = RecurrencePreview(
                rrule_text=phrase,
                freq="MONTHLY",
                byhour=byhour,
                byminute=byminute,
            )
        else:
            weekday_chunk = re.sub(
                r"\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?$",
                "",
                phrase,
                flags=re.IGNORECASE,
            )
            weekday_chunk = re.sub(r"^every\s+", "", weekday_chunk, flags=re.IGNORECASE)
            codes = _normalize_weekdays(weekday_chunk)
            if not codes:
                return remainder, RecurrencePreview(
                    rrule_text=phrase,
                    freq="",
                    ambiguous=True,
                    warning=f"Could not parse weekdays in {phrase!r} — non-recurring.",
                )
            preview = RecurrencePreview(
                rrule_text=phrase,
                freq="WEEKLY",
                byweekday=",".join(codes),
                byhour=byhour,
                byminute=byminute,
            )

        preview.starts_at = starts_at
        preview.ends_at = ends_at
        if bound_warning:
            preview.warning = bound_warning

        if starts_at and ends_at and starts_at.date() > ends_at.date():
            preview.ambiguous = True
            preview.warning = (
                f"Recurrence start {starts_at.date()} is after end {ends_at.date()} "
                "— capture will be non-recurring."
            )
            return remainder, preview

        preview.next_occurrence_at = compute_next_occurrence(
            freq=preview.freq,
            byweekday=preview.byweekday,
            byhour=preview.byhour,
            byminute=preview.byminute,
            interval=preview.interval,
            not_before=starts_at,
        )
        if ends_at and not _occurrence_within_end(preview.next_occurrence_at, ends_at):
            preview.ambiguous = True
            preview.warning = (
                f"First occurrence {preview.next_occurrence_at.date()} is after "
                f"series end {ends_at.date()} — capture will be non-recurring."
            )
        return remainder, preview

    amb = _AMBIGUOUS_RE.search(text)
    if amb:
        phrase = amb.group(0)
        remainder = (text[: amb.start()] + text[amb.end() :]).strip()
        remainder = re.sub(r"\s{2,}", " ", remainder).strip()
        return remainder, RecurrencePreview(
            rrule_text=phrase,
            freq="",
            ambiguous=True,
            warning=f"Ambiguous recurrence {phrase!r} — capture will be non-recurring.",
        )

    return text, None


def attach_recurrence(item: ExecutionItem, preview: RecurrencePreview) -> RecurrenceRule | None:
    """Persist RecurrenceRule for a newly captured item. Skips ambiguous."""
    if preview.ambiguous or not preview.freq:
        return None
    next_at = preview.next_occurrence_at or compute_next_occurrence(
        freq=preview.freq,
        byweekday=preview.byweekday,
        byhour=preview.byhour,
        byminute=preview.byminute,
        interval=preview.interval,
        not_before=preview.starts_at,
    )
    if preview.ends_at and not _occurrence_within_end(next_at, preview.ends_at):
        return None
    rule = RecurrenceRule.objects.create(
        execution_item=item,
        rrule_text=preview.rrule_text[:255],
        freq=preview.freq,
        byweekday=preview.byweekday,
        byhour=preview.byhour,
        interval=preview.interval,
        next_occurrence_at=next_at,
        starts_at=preview.starts_at,
        ends_at=preview.ends_at,
        active=True,
    )
    if item.due_at is None and next_at is not None:
        item.due_at = next_at
        if item.status in (SystemEnums.ItemStatus.INBOX, SystemEnums.ItemStatus.BACKLOG):
            item.status = SystemEnums.ItemStatus.PLANNED
        item.save(update_fields=["due_at", "status", "updated_at"])
    return rule


@transaction.atomic
def advance_recurrence_on_complete(item: ExecutionItem) -> ExecutionItem | None:
    """Spawn next occurrence after ``item`` is COMPLETED; move the rule forward.

    Returns the new item, or None if the item is not an active recurring anchor
    or the next fire would fall after ``ends_at`` (BL-REC-002 — rule deactivated).
    """
    try:
        rule = item.recurrence
    except RecurrenceRule.DoesNotExist:
        return None
    if not rule.active:
        return None

    after = timezone.now()
    if item.due_at and item.due_at > after:
        after = item.due_at

    byminute = 0
    if rule.next_occurrence_at:
        byminute = rule.next_occurrence_at.minute
    elif item.due_at:
        byminute = item.due_at.minute

    next_at = compute_next_occurrence(
        freq=rule.freq,
        byweekday=rule.byweekday,
        byhour=rule.byhour,
        byminute=byminute,
        interval=rule.interval,
        after=after,
        # starts_at only floors the *first* occurrence; later advances ignore it.
    )

    # BL-REC-002: past series end → deactivate, keep completed row as history.
    if rule.ends_at and not _occurrence_within_end(next_at, rule.ends_at):
        rule.active = False
        rule.next_occurrence_at = None
        rule.save(update_fields=["active", "next_occurrence_at"])
        return None

    new_item = ExecutionItem.objects.create(
        title=item.title,
        item_type=item.item_type,
        status=SystemEnums.ItemStatus.PLANNED,
        priority=item.priority,
        urgency=item.urgency,
        due_at=next_at,
        estimated_minutes=item.estimated_minutes,
        parent_item=item.parent_item,
        external_url=item.external_url,
        stack_rank=item.stack_rank,
    )

    for link in item.container_links.all():
        ItemContainerLink.objects.create(
            item=new_item,
            container_id=link.container_id,
            is_primary=link.is_primary,
            pinned=link.pinned,
        )
    new_item.tags.set(item.tags.all())

    rule.execution_item = new_item
    rule.next_occurrence_at = next_at
    rule.save(update_fields=["execution_item", "next_occurrence_at"])

    from lifeos_app.services.reminders import cancel_open_dispatches, rearm_due_reminders

    cancel_open_dispatches(item=item)
    rearm_due_reminders(new_item)

    return new_item
