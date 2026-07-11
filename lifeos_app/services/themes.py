# ==============================================================================
# File: lifeos_app/services/themes.py
# Description: Cockpit theme registry and slug normalization (BL-UI-003)
# Component: Services / Appearance
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Theme mode choices for AppSettings.theme_mode."""

from __future__ import annotations

THEME_HYBRID_DARK = "hybrid_dark"
THEME_SOLARIZED_DARK = "solarized_dark"
THEME_SOLARIZED_LIGHT = "solarized_light"
THEME_LIGHT = "light"

THEME_CHOICES: tuple[tuple[str, str], ...] = (
    (THEME_HYBRID_DARK, "Hybrid Dark"),
    (THEME_SOLARIZED_DARK, "Solarized Dark"),
    (THEME_SOLARIZED_LIGHT, "Solarized Light"),
    (THEME_LIGHT, "Light"),
)

_LEGACY_THEME_MAP = {
    "dark": THEME_HYBRID_DARK,
    "hybrid": THEME_HYBRID_DARK,
    "hybrid dark": THEME_HYBRID_DARK,
    "solarized dark": THEME_SOLARIZED_DARK,
    "solarized light": THEME_SOLARIZED_LIGHT,
    "light": THEME_LIGHT,
}


def resolve_theme_slug(raw: str | None) -> str:
    """Map AppSettings.theme_mode to a data-theme slug."""
    value = (raw or "").strip()
    if not value:
        return THEME_HYBRID_DARK
    lowered = value.lower().replace("_", " ")
    if value in dict(THEME_CHOICES):
        return value
    return _LEGACY_THEME_MAP.get(lowered, THEME_HYBRID_DARK)


def is_valid_theme(slug: str) -> bool:
    return slug in dict(THEME_CHOICES)
