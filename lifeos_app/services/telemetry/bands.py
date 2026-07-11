# ==============================================================================
# File: lifeos_app/services/telemetry/bands.py
# Description: Weather heat + Kp color band resolution (BL-TELE-002 / BL-TELE-003)
# Component: Services / Telemetry
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Map temperature and planetary K-index onto configurable HUD color bands.

Weather cutoffs are stored canonically in °C. Settings UI and HUD resolution
convert to/from °F when ``AppSettings.use_imperial`` is true (DEF-P33-005).
"""

from __future__ import annotations

from dataclasses import dataclass

from lifeos_app.models import AppSettings

# Theme-friendly cool→hot / calm→storm palette (not alert-red for weather cold).
BAND_COLORS = {
    "blue": "#5B8DEF",
    "green": "#3D9B6E",
    "yellow": "#C9A227",
    "red": "#C45C4A",
}

WEATHER_BAND_ORDER = ("blue", "green", "yellow", "red")  # cold → hot
KP_BAND_ORDER = ("blue", "green", "yellow", "red")  # low → storm

# Default exclusive upper bounds in °C (≈ 50 / 75 / 90 °F).
DEFAULT_WEATHER_BAND_COLD_C = 10.0
DEFAULT_WEATHER_BAND_MODERATE_C = 23.9
DEFAULT_WEATHER_BAND_WARM_C = 32.2

# Default Kp exclusive upper bounds (Calm → Storm).
DEFAULT_KP_BAND_BLUE = 3.0
DEFAULT_KP_BAND_GREEN = 5.0
DEFAULT_KP_BAND_YELLOW = 7.0


def default_weather_bands_c() -> tuple[float, float, float]:
    """Canonical weather band defaults (°C)."""
    return (
        DEFAULT_WEATHER_BAND_COLD_C,
        DEFAULT_WEATHER_BAND_MODERATE_C,
        DEFAULT_WEATHER_BAND_WARM_C,
    )


def default_kp_bands() -> tuple[float, float, float]:
    """Canonical Kp band defaults."""
    return (DEFAULT_KP_BAND_BLUE, DEFAULT_KP_BAND_GREEN, DEFAULT_KP_BAND_YELLOW)


def apply_default_weather_bands(settings: AppSettings | None = None) -> AppSettings:
    """Reset weather cutoffs on AppSettings to catalog defaults (°C)."""
    solo = settings or AppSettings.get_solo()
    cold, moderate, warm = default_weather_bands_c()
    solo.weather_band_cold_max = cold
    solo.weather_band_moderate_max = moderate
    solo.weather_band_warm_max = warm
    solo.save(
        update_fields=[
            "weather_band_cold_max",
            "weather_band_moderate_max",
            "weather_band_warm_max",
            "updated_at",
        ]
    )
    return solo


def apply_default_kp_bands(settings: AppSettings | None = None) -> AppSettings:
    """Reset Kp cutoffs on AppSettings to catalog defaults."""
    solo = settings or AppSettings.get_solo()
    blue, green, yellow = default_kp_bands()
    solo.kp_band_blue_max = blue
    solo.kp_band_green_max = green
    solo.kp_band_yellow_max = yellow
    solo.save(
        update_fields=[
            "kp_band_blue_max",
            "kp_band_green_max",
            "kp_band_yellow_max",
            "updated_at",
        ]
    )
    return solo


def apply_default_telemetry_bands(
    *,
    weather: bool = True,
    kp: bool = True,
    settings: AppSettings | None = None,
) -> AppSettings:
    """Reset weather and/or Kp band cutoffs to catalog defaults."""
    solo = settings or AppSettings.get_solo()
    if weather:
        apply_default_weather_bands(solo)
    if kp:
        apply_default_kp_bands(solo)
    return solo


@dataclass(frozen=True)
class ColorBand:
    """Resolved HUD tint for a telemetry value."""

    key: str
    label: str
    color: str


_WEATHER_LABELS = {
    "blue": "Cold",
    "green": "Moderate",
    "yellow": "Warm",
    "red": "Hot",
}

_KP_LABELS = {
    "blue": "Low",
    "green": "Moderate",
    "yellow": "Active",
    "red": "Storm",
}


def celsius_to_fahrenheit(celsius: float) -> float:
    """Convert °C → °F."""
    return float(celsius) * 9.0 / 5.0 + 32.0


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    """Convert °F → °C."""
    return (float(fahrenheit) - 32.0) * 5.0 / 9.0


def _round_temp(value: float) -> float:
    """One-decimal display/storage rounding for band cutoffs."""
    return round(float(value), 1)


def weather_bands_for_display(*, use_imperial: bool, cold_c: float, moderate_c: float, warm_c: float) -> tuple[float, float, float]:
    """Return cutoffs in the unit shown in Settings (F or C)."""
    if use_imperial:
        return (
            _round_temp(celsius_to_fahrenheit(cold_c)),
            _round_temp(celsius_to_fahrenheit(moderate_c)),
            _round_temp(celsius_to_fahrenheit(warm_c)),
        )
    return _round_temp(cold_c), _round_temp(moderate_c), _round_temp(warm_c)


def weather_bands_from_display(
    *,
    use_imperial: bool,
    cold: float,
    moderate: float,
    warm: float,
) -> tuple[float, float, float]:
    """Convert Settings form values (owner unit) to canonical °C storage."""
    if use_imperial:
        cold, moderate, warm = (
            fahrenheit_to_celsius(cold),
            fahrenheit_to_celsius(moderate),
            fahrenheit_to_celsius(warm),
        )
    return _sorted_cutoffs(cold, moderate, warm)


def _sorted_cutoffs(a: float, b: float, c: float) -> tuple[float, float, float]:
    """Ensure three ascending exclusive upper bounds."""
    vals = sorted((float(a), float(b), float(c)))
    # Nudge duplicates so bands remain distinct
    if vals[1] <= vals[0]:
        vals[1] = vals[0] + 0.1
    if vals[2] <= vals[1]:
        vals[2] = vals[1] + 0.1
    return _round_temp(vals[0]), _round_temp(vals[1]), _round_temp(vals[2])


def resolve_weather_band(
    temperature: float | None,
    settings: AppSettings | None = None,
) -> ColorBand | None:
    """Blue/green/yellow/red from temp vs Settings cutoffs.

    ``temperature`` is in the owner's display unit (same as weather fetch).
    Cutoffs in AppSettings are always °C; convert for comparison when imperial.
    """
    if temperature is None:
        return None
    settings = settings or AppSettings.get_solo()
    cold_c, moderate_c, warm_c = _sorted_cutoffs(
        settings.weather_band_cold_max,
        settings.weather_band_moderate_max,
        settings.weather_band_warm_max,
    )
    if settings.use_imperial:
        cold, moderate, warm = weather_bands_for_display(
            use_imperial=True, cold_c=cold_c, moderate_c=moderate_c, warm_c=warm_c
        )
    else:
        cold, moderate, warm = cold_c, moderate_c, warm_c
    if temperature < cold:
        key = "blue"
    elif temperature < moderate:
        key = "green"
    elif temperature < warm:
        key = "yellow"
    else:
        key = "red"
    return ColorBand(key=key, label=_WEATHER_LABELS[key], color=BAND_COLORS[key])


def resolve_kp_band(
    kp_index: float | None,
    settings: AppSettings | None = None,
) -> ColorBand | None:
    """Blue/green/yellow/red from Kp vs Settings cutoffs."""
    if kp_index is None:
        return None
    settings = settings or AppSettings.get_solo()
    blue, green, yellow = _sorted_cutoffs(
        settings.kp_band_blue_max,
        settings.kp_band_green_max,
        settings.kp_band_yellow_max,
    )
    if kp_index < blue:
        key = "blue"
    elif kp_index < green:
        key = "green"
    elif kp_index < yellow:
        key = "yellow"
    else:
        key = "red"
    return ColorBand(key=key, label=_KP_LABELS[key], color=BAND_COLORS[key])


def validate_band_cutoffs(cold: float, moderate: float, warm: float) -> tuple[float, float, float] | None:
    """Return normalized ascending cutoffs, or None if not three finite numbers."""
    try:
        return _sorted_cutoffs(cold, moderate, warm)
    except (TypeError, ValueError):
        return None
