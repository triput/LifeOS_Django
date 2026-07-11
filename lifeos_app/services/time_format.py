# ==============================================================================
# File: lifeos_app/services/time_format.py
# Description: Human-readable duration formatting (BL-TIME-001)
# Component: Services / Time
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Format and parse durations without forcing minute mental math."""

from __future__ import annotations

import re

_DURATION_TOKEN = re.compile(
    r"^(?:(\d+)\s*(?:w|wk|week|weeks))?\s*"
    r"(?:(\d+)\s*(?:d|day|days))?\s*"
    r"(?:(\d+)\s*(?:h|hr|hrs|hour|hours))?\s*"
    r"(?:(\d+)\s*(?:m|min|mins|minute|minutes))?\s*$",
    re.IGNORECASE,
)


def format_duration_minutes(minutes: int) -> str:
    """Render minutes as compact human text (e.g. 90 → '1h 30m')."""
    if minutes <= 0:
        return "0m"
    remaining = minutes
    weeks, remaining = divmod(remaining, 7 * 24 * 60)
    days, remaining = divmod(remaining, 24 * 60)
    hours, mins = divmod(remaining, 60)
    parts: list[str] = []
    if weeks:
        parts.append(f"{weeks}w")
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins or not parts:
        parts.append(f"{mins}m")
    return " ".join(parts)


def format_duration_seconds(seconds: int) -> str:
    """
    Render seconds as human text for UI (backend may still store seconds).

    Under one minute → ``45s``; otherwise delegates to minute formatting
    (e.g. 7200 → ``2h``, 90 → ``1m``).
    """
    if seconds <= 0:
        return "0m"
    if seconds < 60:
        return f"{int(seconds)}s"
    return format_duration_minutes(int(seconds) // 60)


def parse_duration_minutes(text: str) -> int | None:
    """Parse tokens like '2h', '1d 4h', '90m' into minutes."""
    raw = (text or "").strip().lower()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    m = _DURATION_TOKEN.match(raw.replace(",", " "))
    if not m:
        return None
    weeks = int(m.group(1) or 0)
    days = int(m.group(2) or 0)
    hours = int(m.group(3) or 0)
    mins = int(m.group(4) or 0)
    total = weeks * 7 * 24 * 60 + days * 24 * 60 + hours * 60 + mins
    return total if total > 0 else None
