# ==============================================================================
# File: lifeos_app/views/settings.py
# Description: Settings surface — notifications, OAuth, availability (P3 round 3)
# Component: Surfaces / Settings
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Owner settings canvas — webhooks, calendar OAuth client, availability CRUD."""

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from lifeos_app.models import TimeAvailabilityBlock
from lifeos_app.services.appearance import reset_domain_colors, reset_tag_colors, save_appearance_settings
from lifeos_app.services.notify import send_test_webhook
from lifeos_app.services.settings_surface import (
    create_availability_block,
    delete_availability_block,
    resolve_settings_tab,
    reset_telemetry_bands,
    save_general_settings,
    save_google_oauth_settings,
    save_calendar_push_settings,
    save_microsoft_oauth_settings,
    save_notification_settings,
    SaveResult,
    settings_context,
    update_availability_block,
)


def _request_settings_tab(request) -> str:
    """Active tab from POST (HTMX save), GET (?tab=), or default."""
    raw = request.POST.get("settings_tab") or request.GET.get("tab")
    return resolve_settings_tab(raw)


def _render_settings(request, **extra):
    """Full page on GET; HTMX fragment only on POST (avoids nested shell)."""
    if "settings_tab" not in extra:
        extra["settings_tab"] = _request_settings_tab(request)
    ctx = settings_context(settings_tab=extra.pop("settings_tab"))
    ctx.update(extra)
    template = "partials/settings_page.html" if request.htmx else "surfaces/settings.html"
    return render(request, template, ctx)


def _render_save_result(request, result: SaveResult, **extra):
    """Render settings with SaveResult message/ok flags."""
    return _render_settings(
        request,
        settings_message=result.message,
        settings_ok=result.ok,
        **extra,
    )


@login_required
@require_GET
def settings_view(request):
    """Settings canvas — general, notifications, calendar OAuth, availability."""
    return _render_settings(request)


@login_required
@require_POST
def settings_appearance_save_view(request):
    """Save theme mode and domain/tag colors."""
    domain_colors: dict[int, str] = {}
    tag_colors: dict[int, str] = {}
    for key, value in request.POST.items():
        if key.startswith("domain_color_"):
            raw_id = key.removeprefix("domain_color_")
            if raw_id.isdigit():
                domain_colors[int(raw_id)] = value
        elif key.startswith("tag_color_"):
            raw_id = key.removeprefix("tag_color_")
            if raw_id.isdigit():
                tag_colors[int(raw_id)] = value
    result = save_appearance_settings(
        theme_mode=request.POST.get("theme_mode", ""),
        domain_colors=domain_colors,
        tag_colors=tag_colors,
    )
    response = _render_save_result(request, result)
    if result.ok:
        response["HX-Refresh"] = "true"
    return response


@login_required
@require_POST
def settings_appearance_reset_color_view(request):
    """Reset one or all domain/tag colors to seed catalog defaults."""
    kind = request.POST.get("kind", "")
    pk_raw = request.POST.get("pk", "").strip()
    pk = int(pk_raw) if pk_raw.isdigit() else None
    if kind == "domain":
        result = reset_domain_colors(domain_id=pk)
    elif kind == "domains":
        result = reset_domain_colors(domain_id=None)
    elif kind == "tag":
        result = reset_tag_colors(tag_id=pk)
    elif kind == "tags":
        result = reset_tag_colors(tag_id=None)
    else:
        result = SaveResult(ok=False, message="Unknown color reset target.")
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_general_save_view(request):
    """Save timezone, scheduler buffer, location, and weather provider."""
    try:
        buffer = int(request.POST.get("scheduler_buffer_minutes", "10"))
    except ValueError:
        buffer = 10

    def _optional_float(raw: str) -> float | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _optional_int(raw: str) -> int | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    result = save_general_settings(
        timezone=request.POST.get("timezone", ""),
        scheduler_buffer_minutes=buffer,
        location_name=request.POST.get("location_name", ""),
        latitude=_optional_float(request.POST.get("latitude", "")),
        longitude=_optional_float(request.POST.get("longitude", "")),
        weather_provider=request.POST.get("weather_provider", ""),
        openweather_api_key=request.POST.get("openweather_api_key", ""),
        auto_detect_location=request.POST.get("auto_detect_location") == "on",
        use_24h_time=request.POST.get("use_24h_time") == "on",
        use_imperial=request.POST.get("use_imperial") == "on",
        daily_completion_target=_optional_int(request.POST.get("daily_completion_target", "")),
        daily_focus_minutes_target=_optional_int(request.POST.get("daily_focus_minutes_target", "")),
        stability_streak_window_days=_optional_int(request.POST.get("stability_streak_window_days", "")),
        weather_band_cold_max=_optional_float(request.POST.get("weather_band_cold_max", "")),
        weather_band_moderate_max=_optional_float(request.POST.get("weather_band_moderate_max", "")),
        weather_band_warm_max=_optional_float(request.POST.get("weather_band_warm_max", "")),
        kp_band_blue_max=_optional_float(request.POST.get("kp_band_blue_max", "")),
        kp_band_green_max=_optional_float(request.POST.get("kp_band_green_max", "")),
        kp_band_yellow_max=_optional_float(request.POST.get("kp_band_yellow_max", "")),
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_bands_reset_view(request):
    """Reset weather and/or Kp telemetry band thresholds to catalog defaults."""
    result = reset_telemetry_bands(kind=request.POST.get("kind", "all"))
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_geocode_view(request):
    """Forward-geocode location_name → lat/lon JSON (BL-TELE-005)."""
    from lifeos_app.services.telemetry.geocode import geocode_place

    raw = (request.POST.get("location_name") or "").strip()
    result = geocode_place(raw)
    payload: dict = {
        "ok": result.ok,
        "message": result.message,
    }
    if result.hit:
        payload["latitude"] = result.hit.latitude
        payload["longitude"] = result.hit.longitude
        payload["label"] = result.hit.label
    if result.candidates:
        payload["candidates"] = [
            {"label": c.label, "latitude": c.latitude, "longitude": c.longitude}
            for c in result.candidates
        ]
    status = 200 if result.ok else 400
    # Empty query is a client validation miss, not a server error
    if not raw:
        status = 400
    return JsonResponse(payload, status=status)


@login_required
@require_POST
def settings_notifications_save_view(request):
    """Save webhook notification policy."""
    try:
        lead = int(request.POST.get("reminder_lead_minutes", "15"))
    except ValueError:
        lead = 15
    result = save_notification_settings(
        notifications_enabled=request.POST.get("notifications_enabled") == "on",
        notification_channel=request.POST.get("notification_channel", "ntfy"),
        notification_webhook_url=request.POST.get("notification_webhook_url", ""),
        notification_webhook_token=request.POST.get("notification_webhook_token", ""),
        reminder_lead_minutes=lead,
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_webhook_test_view(request):
    """POST a test payload to the configured webhook URL."""
    result = send_test_webhook()
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_google_oauth_save_view(request):
    """Save Google OAuth client credentials."""
    result = save_google_oauth_settings(
        client_id=request.POST.get("google_oauth_client_id", ""),
        client_secret=request.POST.get("google_oauth_client_secret", ""),
        redirect_uri=request.POST.get("google_oauth_redirect_uri", ""),
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_calendar_push_save_view(request):
    """Toggle feature-flagged Google allocation push (P5-03)."""
    result = save_calendar_push_settings(
        enabled=request.POST.get("calendar_push_enabled") in ("1", "on", "true", "True"),
    )
    return _render_save_result(request, result)


@login_required
@require_GET
def settings_availability_edit_view(request, block_id: int):
    """Open inline edit form for an availability block."""
    if not TimeAvailabilityBlock.objects.filter(pk=block_id).exists():
        return _render_settings(
            request,
            settings_message="Availability block not found.",
            settings_ok=False,
            settings_tab="availability",
        )
    return _render_settings(request, editing_availability_id=block_id, settings_tab="availability")


@login_required
@require_POST
def settings_availability_update_view(request, block_id: int):
    """Save changes to an availability block."""
    days = set(request.POST.getlist("days"))
    domain_raw = request.POST.get("domain_id", "").strip()
    domain_id = int(domain_raw) if domain_raw.isdigit() else None
    result = update_availability_block(
        block_id,
        name=request.POST.get("name", ""),
        domain_id=domain_id,
        start_time=request.POST.get("start_time", "09:00"),
        end_time=request.POST.get("end_time", "17:00"),
        days=days,
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_microsoft_oauth_save_view(request):
    """Save Microsoft Graph OAuth client credentials."""
    result = save_microsoft_oauth_settings(
        client_id=request.POST.get("microsoft_oauth_client_id", ""),
        client_secret=request.POST.get("microsoft_oauth_client_secret", ""),
        redirect_uri=request.POST.get("microsoft_oauth_redirect_uri", ""),
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_availability_create_view(request):
    """Add a weekly availability block."""
    days = set(request.POST.getlist("days"))
    domain_raw = request.POST.get("domain_id", "").strip()
    domain_id = int(domain_raw) if domain_raw.isdigit() else None
    result = create_availability_block(
        name=request.POST.get("name", ""),
        domain_id=domain_id,
        start_time=request.POST.get("start_time", "09:00"),
        end_time=request.POST.get("end_time", "17:00"),
        days=days,
    )
    return _render_save_result(request, result)


@login_required
@require_POST
def settings_availability_delete_view(request, block_id: int):
    """Delete an availability block."""
    result = delete_availability_block(block_id)
    return _render_save_result(request, result)
