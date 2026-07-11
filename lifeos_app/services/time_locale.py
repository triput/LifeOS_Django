# ==============================================================================
# File: lifeos_app/services/time_locale.py
# Description: IANA timezone list + clock/unit locale helpers (BL-TIME-002/003)
# Component: Services / Time
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Timezone catalog and display-format helpers for Settings locale prefs."""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

# Prefer these near the top of the picker for common owner locales.
_PINNED_TIMEZONES = (
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Denver",
    "America/Chicago",
    "America/New_York",
    "UTC",
    "Europe/London",
    "Europe/Paris",
    "Asia/Tokyo",
    "Australia/Sydney",
)


@lru_cache(maxsize=1)
def iana_timezone_choices() -> tuple[str, ...]:
    """Sorted IANA zone names with common zones pinned first."""
    all_zones = sorted(available_timezones())
    pinned = [z for z in _PINNED_TIMEZONES if z in all_zones]
    rest = [z for z in all_zones if z not in pinned]
    return tuple(pinned + rest)


def is_valid_timezone(name: str) -> bool:
    """True when name is a loadable IANA zone."""
    raw = (name or "").strip()
    if not raw:
        return False
    try:
        ZoneInfo(raw)
        return True
    except Exception:
        return False


def normalize_timezone(name: str, *, fallback: str = "UTC") -> str:
    """Return a valid IANA name or fallback."""
    raw = (name or "").strip()[:64]
    if is_valid_timezone(raw):
        return raw
    if is_valid_timezone(fallback):
        return fallback
    return "UTC"


def clock_format(*, use_24h: bool, short: bool = False) -> str:
    """Django ``time`` filter format string for owner clock preference."""
    if use_24h:
        return "H:i"
    return "g:i" if short else "g:i A"
