# ==============================================================================
# File: lifeos_app/views/calendar.py
# Description: Calendar OAuth + sync endpoints (Google + Microsoft Graph)
# Component: Surfaces / Calendar
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Google and Microsoft calendar connect and read-only pull."""

import json
import secrets
from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from lifeos_app.models import SystemEnums
from lifeos_app.services.calendar_config import oauth_configured, oauth_setup_message, validate_oauth_config
from lifeos_app.services.calendar_oauth import (
    exchange_code as google_exchange_code,
    oauth_session_key,
    save_integration_credentials,
    start_authorization as google_start_authorization,
)
from lifeos_app.services.calendar_sync import (
    get_active_integration,
    pull_calendar,
    refresh_synced_calendars,
    set_calendar_color,
    set_calendar_sync_enabled,
)
from lifeos_app.services.microsoft_calendar_oauth import (
    connect_microsoft_account,
    start_authorization as microsoft_start_authorization,
)
from lifeos_app.services.plan import calendar_is_live, planner_context, provider_calendar_context


def _oauth_redirect_uri(request, provider: str) -> str:
    """Stored redirect URI or auto-detect from the current request."""
    if provider == SystemEnums.CalendarProvider.MICROSOFT:
        return request.build_absolute_uri(reverse("calendar-microsoft-oauth-callback"))
    return request.build_absolute_uri(reverse("calendar-oauth-callback"))


def _calendar_panel_response(request, provider: str, **extra):
    """Render one provider's planner calendar sidebar partial."""
    ctx = provider_calendar_context(provider, request=request)
    ctx.update(extra)
    return render(request, "partials/plan_calendar_provider_panel.html", {"p": ctx})


def _start_oauth(request, provider: str):
    """Redirect owner to provider OAuth consent."""
    redirect_uri = _oauth_redirect_uri(request, provider)
    errors = validate_oauth_config(provider=provider, redirect_uri=redirect_uri)
    if errors:
        return redirect(
            f"{reverse('canvas-plan')}?calendar_error=oauth_invalid&calendar_provider={provider}"
            f"&calendar_error_detail={quote(errors[0][:120])}"
        )
    if not oauth_configured(provider=provider, redirect_uri=redirect_uri):
        return redirect(
            f"{reverse('canvas-plan')}?calendar_error=oauth_not_configured&calendar_provider={provider}"
        )
    state = secrets.token_urlsafe(32)
    if provider == SystemEnums.CalendarProvider.MICROSOFT:
        auth = microsoft_start_authorization(state, redirect_uri=redirect_uri)
    else:
        auth = google_start_authorization(state, redirect_uri=redirect_uri)
    request.session[oauth_session_key(provider, "state")] = state
    request.session[oauth_session_key(provider, "redirect")] = redirect_uri
    request.session[oauth_session_key(provider, "code_verifier")] = auth.code_verifier
    request.session.modified = True
    return redirect(auth.url)


def _oauth_callback(request, provider: str):
    """OAuth callback — store refresh token and redirect to Planner."""
    state = request.session.pop(oauth_session_key(provider, "state"), None)
    redirect_uri = request.session.pop(oauth_session_key(provider, "redirect"), None) or _oauth_redirect_uri(
        request, provider
    )
    code_verifier = request.session.pop(oauth_session_key(provider, "code_verifier"), None)
    if not state or state != request.GET.get("state"):
        return HttpResponseBadRequest("Invalid OAuth state.")
    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("Missing authorization code.")
    try:
        if provider == SystemEnums.CalendarProvider.MICROSOFT:
            integration = connect_microsoft_account(
                code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier or "",
            )
        else:
            credentials = google_exchange_code(
                code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier or "",
            )
            integration = save_integration_credentials(
                credentials,
                provider=SystemEnums.CalendarProvider.GOOGLE,
            )
        try:
            refresh_synced_calendars(integration)
        except Exception:  # noqa: BLE001 — connect succeeded; list refresh can retry in UI
            pass
    except Exception as exc:  # noqa: BLE001 — surface OAuth errors on Planner
        detail = str(exc)[:200]
        return redirect(
            f"{reverse('canvas-plan')}?calendar_error=oauth_exchange&calendar_provider={provider}"
            f"&calendar_error_detail={quote(detail)}"
        )
    return redirect(f"{reverse('canvas-plan')}?calendar_connected=1&calendar_provider={provider}")


@login_required
@require_GET
def calendar_auth_view(request):
    """Redirect owner to Google OAuth consent."""
    return _start_oauth(request, SystemEnums.CalendarProvider.GOOGLE)


@login_required
@require_GET
def calendar_microsoft_auth_view(request):
    """Redirect owner to Microsoft OAuth consent."""
    return _start_oauth(request, SystemEnums.CalendarProvider.MICROSOFT)


@login_required
@require_GET
def calendar_oauth_callback_view(request):
    """Google OAuth callback."""
    return _oauth_callback(request, SystemEnums.CalendarProvider.GOOGLE)


@login_required
@require_GET
def calendar_microsoft_oauth_callback_view(request):
    """Microsoft OAuth callback."""
    return _oauth_callback(request, SystemEnums.CalendarProvider.MICROSOFT)


def _sync_calendar(request, provider: str):
    """Pull events for one provider; refresh planner timeline on success."""
    result = pull_calendar(provider=provider)
    ctx = planner_context(request=request)
    panel = provider_calendar_context(provider, request=request)
    panel["calendar_message"] = result.message
    panel["calendar_ok"] = result.ok
    panel["calendar_live"] = calendar_is_live(panel.get("calendar_integration"))
    response = render(
        request,
        "partials/plan_calendar_provider_panel.html",
        {"p": panel},
    )
    if result.ok:
        timeline = render(request, "partials/plan_timeline.html", ctx)
        response.content = (
            response.content
            + b'<div id="plan-timeline" hx-swap-oob="innerHTML">'
            + timeline.content
            + b"</div>"
        )
        response["HX-Trigger"] = json.dumps({"plan-reload": True})
    return response


@login_required
@require_POST
def calendar_sync_view(request):
    """Pull Google calendar events."""
    return _sync_calendar(request, SystemEnums.CalendarProvider.GOOGLE)


@login_required
@require_POST
def calendar_microsoft_sync_view(request):
    """Pull Microsoft calendar events."""
    return _sync_calendar(request, SystemEnums.CalendarProvider.MICROSOFT)


def _refresh_calendar_list(request, provider: str):
    integration = get_active_integration(provider=provider)
    if not integration or not calendar_is_live(integration):
        label = "Google" if provider == SystemEnums.CalendarProvider.GOOGLE else "Outlook"
        return _calendar_panel_response(
            request,
            provider,
            calendar_message=f"Connect {label} Calendar first.",
            calendar_ok=False,
        )
    try:
        count = refresh_synced_calendars(integration)
        return _calendar_panel_response(
            request,
            provider,
            calendar_message=f"Found {count} calendar(s). Check the ones to sync.",
            calendar_ok=True,
        )
    except Exception as exc:  # noqa: BLE001
        return _calendar_panel_response(
            request,
            provider,
            calendar_message=str(exc)[:200],
            calendar_ok=False,
        )


@login_required
@require_POST
def calendar_refresh_list_view(request):
    """Re-fetch Google calendar list."""
    return _refresh_calendar_list(request, SystemEnums.CalendarProvider.GOOGLE)


@login_required
@require_POST
def calendar_microsoft_refresh_list_view(request):
    """Re-fetch Microsoft calendar list."""
    return _refresh_calendar_list(request, SystemEnums.CalendarProvider.MICROSOFT)


@login_required
@require_POST
def calendar_toggle_view(request, calendar_pk: int):
    """Enable or disable sync for one discovered calendar."""
    from lifeos_app.models import SyncedCalendar

    synced = SyncedCalendar.objects.select_related("integration").filter(pk=calendar_pk).first()
    if not synced:
        return HttpResponseBadRequest("Unknown calendar.")
    provider = synced.integration.provider
    enabled = request.POST.get("sync_enabled", "").lower() in {"1", "true", "on", "yes"}
    set_calendar_sync_enabled(synced, enabled=enabled)
    return _calendar_panel_response(request, provider)


@login_required
@require_POST
def calendar_color_view(request, calendar_pk: int):
    """Owner color override for a synced calendar (BL-CAL-004)."""
    from lifeos_app.models import SyncedCalendar

    synced = SyncedCalendar.objects.select_related("integration").filter(pk=calendar_pk).first()
    if not synced:
        return HttpResponseBadRequest("Unknown calendar.")
    set_calendar_color(synced, color=request.POST.get("color", ""))
    if request.POST.get("return") == "grid":
        from lifeos_app.views.calendar_grid import _grid_context

        return render(request, "partials/plan_calendar_grid_page.html", _grid_context(request))
    return _calendar_panel_response(request, synced.integration.provider)


@login_required
@require_GET
def calendar_status_view(request):
    """HTMX partial — both calendar provider panels on Planner."""
    return render(
        request,
        "partials/plan_calendar_panel.html",
        planner_context(request=request),
    )
