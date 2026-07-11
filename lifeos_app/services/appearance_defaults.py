# ==============================================================================
# File: lifeos_app/services/appearance_defaults.py
# Description: Canonical default domain/tag colors (seed catalog + model fallbacks)
# Component: Services / Appearance
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Default taxonomy colors — keep aligned with seed_data catalog."""

from __future__ import annotations

from lifeos_app.models import DomainCategory, Tag

# Dusty Jewel palette from seed_data / BL-UI-001
DOMAIN_COLORS_BY_SLUG: dict[str, str] = {
    "tech": "#8B9EF5",
    "theater": "#B794F6",
    "academy": "#4EDFD4",
    "home": "#5EEAB8",
    "governance": "#9B82E8",
}

TAG_COLORS_BY_NAME: dict[str, str] = {
    "deep-work": "#5EEAB8",
    "quick-win": "#FACC15",
    "blocked-ext": "#F87171",
    "lab": "#4EDFD4",
    "rehearsal": "#B794F6",
    "errand": "#5EEAB8",
    "compliance": "#9B82E8",
}

DOMAIN_COLOR_FALLBACK = "#64748B"
TAG_COLOR_FALLBACK = "#A1A1AA"


def default_domain_color(domain: DomainCategory) -> str:
    """Resolved default hex for a domain (seed slug map, else model fallback)."""
    return DOMAIN_COLORS_BY_SLUG.get(domain.slug, DOMAIN_COLOR_FALLBACK)


def default_tag_color(tag: Tag) -> str:
    """Resolved default hex for a tag (seed name map, else model fallback)."""
    return TAG_COLORS_BY_NAME.get(tag.name, TAG_COLOR_FALLBACK)
