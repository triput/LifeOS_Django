# ==============================================================================
# File: lifeos_app/middleware.py
# Description: Owner-only access middleware and timezone activation
# Component: Core / Security Middleware
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Single-owner enforcement for the LifeOS V2 cockpit."""

from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import Resolver404, resolve


class OwnerOnlyAccessMiddleware:
    """NFR-SEC-001/002: session auth + superuser-only app access."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        static_url = getattr(settings, "STATIC_URL", "/static/") or "/static/"
        if request.path.startswith(static_url):
            return self.get_response(request)

        try:
            view_name = resolve(request.path).view_name
        except Resolver404:
            view_name = None

        exempt_view_names = {
            "login",
            "logout",
            "setup-owner",
            "admin:login",
            "admin:logout",
            "password_reset",
            "password_reset_done",
            "password_reset_confirm",
            "password_reset_complete",
        }
        exempt_prefixes = ("/admin/", "/login/", "/logout/", "/setup/", "/password-reset")
        is_exempt = view_name in exempt_view_names or request.path.startswith(exempt_prefixes)

        if is_exempt:
            return self.get_response(request)

        if not request.user.is_authenticated:
            return redirect(settings.LOGIN_URL)

        if not request.user.is_superuser:
            return HttpResponseForbidden("Forbidden: You are not authorized to access LifeOS.")

        # Activate owner timezone for request-local rendering
        try:
            import zoneinfo

            from django.utils import timezone as dj_tz

            from .models import AppSettings

            app_settings = AppSettings.get_solo()
            if app_settings.timezone:
                dj_tz.activate(zoneinfo.ZoneInfo(app_settings.timezone))
        except Exception:
            pass

        return self.get_response(request)
