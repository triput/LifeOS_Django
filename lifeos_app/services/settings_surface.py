# ==============================================================================
# File: lifeos_app/services/settings_surface.py
# Description: Settings surface save helpers (SURF-SETTINGS)
# Component: Services / Settings
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Load and persist owner settings from the Settings canvas."""

from __future__ import annotations

from dataclasses import dataclass

from lifeos_app.models import AppSettings, DomainCategory, SystemEnums, TimeAvailabilityBlock
from lifeos_app.services.calendar_config import clean_secret

# BL-UI-004 — Settings tab ids and labels (order = nav order)
SETTINGS_TABS: tuple[tuple[str, str], ...] = (
    ("general", "General"),
    ("notifications", "Notifications"),
    ("calendars", "Calendars"),
    ("availability", "Availability"),
    ("appearance", "Appearance"),
    ("templates", "Templates"),
)
SETTINGS_TAB_IDS = {tab_id for tab_id, _ in SETTINGS_TABS}
DEFAULT_SETTINGS_TAB = "general"


@dataclass
class SaveResult:
    """Outcome of a settings form save."""

    ok: bool
    message: str = ""


def resolve_settings_tab(raw: str | None) -> str:
    """Normalize a tab id; unknown values fall back to General."""
    tab = (raw or "").strip().lower()
    if tab in SETTINGS_TAB_IDS:
        return tab
    return DEFAULT_SETTINGS_TAB


def reset_telemetry_bands(*, kind: str = "all") -> SaveResult:
    """Restore weather and/or Kp color-band cutoffs to catalog defaults."""
    from lifeos_app.services.telemetry.bands import (
        apply_default_kp_bands,
        apply_default_telemetry_bands,
        apply_default_weather_bands,
    )

    kind = (kind or "all").strip().lower()
    if kind == "weather":
        apply_default_weather_bands()
        return SaveResult(ok=True, message="Weather band thresholds reset to defaults.")
    if kind == "kp":
        apply_default_kp_bands()
        return SaveResult(ok=True, message="Kp band thresholds reset to defaults.")
    if kind == "all":
        apply_default_telemetry_bands(weather=True, kp=True)
        return SaveResult(ok=True, message="Telemetry color bands reset to defaults.")
    return SaveResult(ok=False, message="Unknown band reset target.")


def settings_context(*, settings_tab: str | None = None) -> dict:
    """Template context for SURF-SETTINGS."""
    from lifeos_app.services.appearance import appearance_context
    from lifeos_app.services.time_locale import iana_timezone_choices

    from lifeos_app.services.telemetry.bands import (
        default_kp_bands,
        default_weather_bands_c,
        weather_bands_for_display,
    )

    tab = resolve_settings_tab(settings_tab)
    solo = AppSettings.get_solo()
    from lifeos_app.services.templates_workspace import list_active_templates

    cold_d, mod_d, warm_d = weather_bands_for_display(
        use_imperial=bool(solo.use_imperial),
        cold_c=solo.weather_band_cold_max,
        moderate_c=solo.weather_band_moderate_max,
        warm_c=solo.weather_band_warm_max,
    )
    def_cold_c, def_mod_c, def_warm_c = default_weather_bands_c()
    def_cold_d, def_mod_d, def_warm_d = weather_bands_for_display(
        use_imperial=bool(solo.use_imperial),
        cold_c=def_cold_c,
        moderate_c=def_mod_c,
        warm_c=def_warm_c,
    )
    def_kp_blue, def_kp_green, def_kp_yellow = default_kp_bands()
    ctx = {
        "surface": "settings",
        "settings_obj": solo,
        "availability_blocks": TimeAvailabilityBlock.objects.select_related("domain").order_by(
            "name"
        ),
        "domains": DomainCategory.objects.filter(is_active=True).order_by("name"),
        "settings_tabs": SETTINGS_TABS,
        "settings_tab": tab,
        "workspace_templates": list_active_templates(),
        "timezone_choices": iana_timezone_choices(),
        # Display-unit weather band fields (canonical storage is °C).
        "weather_band_cold_display": cold_d,
        "weather_band_moderate_display": mod_d,
        "weather_band_warm_display": warm_d,
        "weather_band_default_display": (def_cold_d, def_mod_d, def_warm_d),
        "kp_band_defaults": (def_kp_blue, def_kp_green, def_kp_yellow),
    }
    ctx.update(appearance_context())
    ctx["weather_provider_choices"] = SystemEnums.WeatherProvider.choices
    return ctx


def save_general_settings(
    *,
    timezone: str,
    scheduler_buffer_minutes: int,
    location_name: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    weather_provider: str = "",
    openweather_api_key: str = "",
    auto_detect_location: bool = False,
    use_24h_time: bool = False,
    use_imperial: bool = True,
    daily_completion_target: int | None = None,
    daily_focus_minutes_target: int | None = None,
    stability_streak_window_days: int | None = None,
    weather_band_cold_max: float | None = None,
    weather_band_moderate_max: float | None = None,
    weather_band_warm_max: float | None = None,
    kp_band_blue_max: float | None = None,
    kp_band_green_max: float | None = None,
    kp_band_yellow_max: float | None = None,
) -> SaveResult:
    """Persist general scheduling, locale, location, and weather preferences."""
    from django.utils import timezone as dj_tz
    from zoneinfo import ZoneInfo

    from lifeos_app.services.telemetry.bands import validate_band_cutoffs, weather_bands_from_display
    from lifeos_app.services.time_locale import is_valid_timezone, normalize_timezone

    solo = AppSettings.get_solo()
    prev_lat, prev_lon = solo.latitude, solo.longitude
    tz_raw = (timezone or solo.timezone).strip()[:64]
    if not is_valid_timezone(tz_raw):
        return SaveResult(
            ok=False,
            message=f"Unknown timezone “{tz_raw}”. Pick an IANA zone (e.g. America/Phoenix).",
        )
    solo.timezone = normalize_timezone(tz_raw, fallback=solo.timezone)
    solo.scheduler_buffer_minutes = max(0, min(scheduler_buffer_minutes, 120))
    solo.location_name = (location_name or solo.location_name).strip()[:255]
    if latitude is not None:
        solo.latitude = max(-90.0, min(90.0, latitude))
    if longitude is not None:
        solo.longitude = max(-180.0, min(180.0, longitude))
    valid_providers = {c.value for c in SystemEnums.WeatherProvider}
    provider = (weather_provider or SystemEnums.WeatherProvider.AUTO).strip()
    solo.weather_provider = provider if provider in valid_providers else SystemEnums.WeatherProvider.AUTO
    secret = clean_secret(openweather_api_key or "")
    if secret:
        solo.openweather_api_key = secret
    solo.auto_detect_location = bool(auto_detect_location)
    solo.use_24h_time = bool(use_24h_time)
    solo.use_imperial = bool(use_imperial)
    if daily_completion_target is not None:
        solo.daily_completion_target = max(1, min(int(daily_completion_target), 100))
    if daily_focus_minutes_target is not None:
        solo.daily_focus_minutes_target = max(1, min(int(daily_focus_minutes_target), 24 * 60))
    if stability_streak_window_days is not None:
        solo.stability_streak_window_days = max(1, min(int(stability_streak_window_days), 90))

    # Form posts cutoffs in the owner's display unit; persist canonical °C.
    if None not in (weather_band_cold_max, weather_band_moderate_max, weather_band_warm_max):
        try:
            weather_cut = weather_bands_from_display(
                use_imperial=solo.use_imperial,
                cold=weather_band_cold_max,
                moderate=weather_band_moderate_max,
                warm=weather_band_warm_max,
            )
        except (TypeError, ValueError):
            weather_cut = None
        if weather_cut is None:
            return SaveResult(ok=False, message="Weather band thresholds must be numbers.")
        solo.weather_band_cold_max, solo.weather_band_moderate_max, solo.weather_band_warm_max = weather_cut

    if None not in (kp_band_blue_max, kp_band_green_max, kp_band_yellow_max):
        kp_cut = validate_band_cutoffs(kp_band_blue_max, kp_band_green_max, kp_band_yellow_max)
        if kp_cut is None:
            return SaveResult(ok=False, message="Kp band thresholds must be numbers.")
        solo.kp_band_blue_max, solo.kp_band_green_max, solo.kp_band_yellow_max = kp_cut

    solo.save(
        update_fields=[
            "timezone",
            "scheduler_buffer_minutes",
            "location_name",
            "latitude",
            "longitude",
            "weather_provider",
            "openweather_api_key",
            "auto_detect_location",
            "use_24h_time",
            "use_imperial",
            "daily_completion_target",
            "daily_focus_minutes_target",
            "stability_streak_window_days",
            "weather_band_cold_max",
            "weather_band_moderate_max",
            "weather_band_warm_max",
            "kp_band_blue_max",
            "kp_band_green_max",
            "kp_band_yellow_max",
            "updated_at",
        ]
    )
    # Drop stale weather snapshots when coordinates change (BL-TELE-004).
    if (solo.latitude, solo.longitude) != (prev_lat, prev_lon):
        from lifeos_app.services.telemetry.weather import invalidate_weather_cache_for_coords

        invalidate_weather_cache_for_coords(prev_lat, prev_lon)
        invalidate_weather_cache_for_coords(solo.latitude, solo.longitude)
    # Activate immediately so the same request / next HTMX fragment uses the new TZ.
    try:
        dj_tz.activate(ZoneInfo(solo.timezone))
    except Exception:
        pass
    return SaveResult(ok=True, message="General settings saved.")


def save_notification_settings(
    *,
    notifications_enabled: bool,
    notification_channel: str,
    notification_webhook_url: str,
    notification_webhook_token: str,
    reminder_lead_minutes: int,
) -> SaveResult:
    """Persist outbound webhook notification policy."""
    solo = AppSettings.get_solo()
    solo.notifications_enabled = notifications_enabled
    valid_channels = {c.value for c in SystemEnums.NotificationChannel}
    channel = (notification_channel or SystemEnums.NotificationChannel.NTFY).strip()
    solo.notification_channel = channel if channel in valid_channels else SystemEnums.NotificationChannel.NTFY
    solo.notification_webhook_url = (notification_webhook_url or "").strip()
    solo.notification_webhook_token = clean_secret(notification_webhook_token or "")
    solo.reminder_lead_minutes = max(1, min(reminder_lead_minutes, 10_080))
    solo.save(
        update_fields=[
            "notifications_enabled",
            "notification_channel",
            "notification_webhook_url",
            "notification_webhook_token",
            "reminder_lead_minutes",
            "updated_at",
        ]
    )
    return SaveResult(ok=True, message="Notification settings saved.")


def save_google_oauth_settings(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> SaveResult:
    """Persist Google OAuth client credentials (DB, not git)."""
    solo = AppSettings.get_solo()
    solo.google_oauth_client_id = clean_secret(client_id or "")
    secret = clean_secret(client_secret or "")
    if secret:
        solo.google_oauth_client_secret = secret
    solo.google_oauth_redirect_uri = (redirect_uri or "").strip()[:512]
    solo.save(
        update_fields=[
            "google_oauth_client_id",
            "google_oauth_client_secret",
            "google_oauth_redirect_uri",
            "updated_at",
        ]
    )
    return SaveResult(ok=True, message="Google Calendar OAuth client saved.")


def save_calendar_push_settings(*, enabled: bool) -> SaveResult:
    """Toggle P5-03 Google allocation push. Reconnect required for write scope."""
    solo = AppSettings.get_solo()
    solo.calendar_push_enabled = bool(enabled)
    solo.save(update_fields=["calendar_push_enabled", "updated_at"])
    if solo.calendar_push_enabled:
        return SaveResult(
            ok=True,
            message=(
                "Calendar push enabled — reconnect Google from Planner to grant write access."
            ),
        )
    return SaveResult(ok=True, message="Calendar push disabled.")


def save_microsoft_oauth_settings(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> SaveResult:
    """Persist Microsoft Graph OAuth client credentials (DB, not git)."""
    solo = AppSettings.get_solo()
    solo.microsoft_oauth_client_id = clean_secret(client_id or "")
    secret = clean_secret(client_secret or "")
    if secret:
        solo.microsoft_oauth_client_secret = secret
    solo.microsoft_oauth_redirect_uri = (redirect_uri or "").strip()[:512]
    solo.save(
        update_fields=[
            "microsoft_oauth_client_id",
            "microsoft_oauth_client_secret",
            "microsoft_oauth_redirect_uri",
            "updated_at",
        ]
    )
    return SaveResult(ok=True, message="Microsoft Calendar OAuth client saved.")


def _apply_availability_fields(
    block: TimeAvailabilityBlock,
    *,
    name: str,
    domain_id: int | None,
    start_time: str,
    end_time: str,
    days: set[str],
) -> SaveResult:
    """Validate and apply shared availability block fields."""
    name = (name or "").strip()
    if not name:
        return SaveResult(ok=False, message="Availability block name is required.")
    domain = None
    if domain_id:
        domain = DomainCategory.objects.filter(pk=domain_id).first()
    block.name = name[:100]
    block.domain = domain
    block.start_time = start_time or "09:00"
    block.end_time = end_time or "17:00"
    block.day_monday = "mon" in days
    block.day_tuesday = "tue" in days
    block.day_wednesday = "wed" in days
    block.day_thursday = "thu" in days
    block.day_friday = "fri" in days
    block.day_saturday = "sat" in days
    block.day_sunday = "sun" in days
    block.save()
    return SaveResult(ok=True, message="")


def create_availability_block(
    *,
    name: str,
    domain_id: int | None,
    start_time: str,
    end_time: str,
    days: set[str],
) -> SaveResult:
    """Create a weekly availability window for the scheduler."""
    block = TimeAvailabilityBlock()
    result = _apply_availability_fields(
        block,
        name=name,
        domain_id=domain_id,
        start_time=start_time,
        end_time=end_time,
        days=days,
    )
    if not result.ok:
        return result
    return SaveResult(ok=True, message=f"Added availability block “{block.name}”.")


def update_availability_block(
    block_id: int,
    *,
    name: str,
    domain_id: int | None,
    start_time: str,
    end_time: str,
    days: set[str],
) -> SaveResult:
    """Update an existing weekly availability window."""
    block = TimeAvailabilityBlock.objects.filter(pk=block_id).first()
    if not block:
        return SaveResult(ok=False, message="Availability block not found.")
    result = _apply_availability_fields(
        block,
        name=name,
        domain_id=domain_id,
        start_time=start_time,
        end_time=end_time,
        days=days,
    )
    if not result.ok:
        return result
    return SaveResult(ok=True, message=f"Updated availability block “{block.name}”.")


def delete_availability_block(block_id: int) -> SaveResult:
    """Remove an availability block."""
    deleted, _ = TimeAvailabilityBlock.objects.filter(pk=block_id).delete()
    if not deleted:
        return SaveResult(ok=False, message="Availability block not found.")
    return SaveResult(ok=True, message="Availability block removed.")
