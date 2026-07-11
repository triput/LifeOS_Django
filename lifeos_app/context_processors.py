# ==============================================================================
# File: lifeos_app/context_processors.py
# Description: Global template context for AppSettings and shell chrome
# Component: Core / Context Processor
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Template context helpers for the V2 cockpit shell."""

from .models import AppSettings
from lifeos_app.services.themes import resolve_theme_slug
from lifeos_app.services.time_locale import clock_format


def global_settings(request):
    """Expose singleton AppSettings and locale display helpers to all templates."""
    try:
        settings_obj = AppSettings.get_solo()
    except Exception:
        settings_obj = None
    theme_slug = resolve_theme_slug(settings_obj.theme_mode if settings_obj else "")
    use_24h = bool(settings_obj.use_24h_time) if settings_obj else False
    return {
        "app_settings": settings_obj,
        "theme_slug": theme_slug,
        "clock_format": clock_format(use_24h=use_24h, short=False),
        "clock_format_short": clock_format(use_24h=use_24h, short=True),
        "use_imperial": bool(settings_obj.use_imperial) if settings_obj else True,
    }
