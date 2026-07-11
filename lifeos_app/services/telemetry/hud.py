# ==============================================================================
# File: lifeos_app/services/telemetry/hud.py
# Description: Tier 4 telemetry HUD context builder
# Component: Services / Telemetry
# Version: 1.2 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Assemble weather + space weather for the lazy-loaded Home HUD."""

from __future__ import annotations

from lifeos_app.models import AppSettings
from lifeos_app.services.telemetry.bands import resolve_kp_band, resolve_weather_band
from lifeos_app.services.telemetry.space_weather import fetch_space_weather
from lifeos_app.services.telemetry.weather import fetch_weather, resolve_weather_provider


def build_telemetry_hud() -> dict:
    """Template context for the Tier 4 telemetry partial."""
    settings = AppSettings.get_solo()
    weather = fetch_weather(settings)
    space = fetch_space_weather()
    return {
        "weather": weather,
        "space_weather": space,
        "weather_band": resolve_weather_band(weather.temperature, settings),
        "kp_band": resolve_kp_band(space.kp_index, settings),
        "location_name": settings.location_name,
        "timezone": settings.timezone,
        "weather_provider": resolve_weather_provider(settings),
    }


def warm_telemetry_caches() -> dict:
    """Force-refresh weather + space weather into cache (Celery Beat / cron)."""
    settings = AppSettings.get_solo()
    weather = fetch_weather(settings, force_refresh=True)
    space = fetch_space_weather(force_refresh=True)
    return {
        "weather_provider": weather.provider,
        "weather_error": weather.error or "",
        "space_error": space.error or "",
        "kp_index": space.kp_index,
    }
