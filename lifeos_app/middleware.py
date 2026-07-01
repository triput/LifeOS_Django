# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/middleware.py
# Description: Middleware enforcing single-owner access controls across all views
# Component: Core / Security Middleware
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-30
# ==============================================================================
"""Security middleware to restrict app access to the single configured owner."""

from django.shortcuts import redirect
from django.urls import resolve, Resolver404
from django.conf import settings
from django.http import HttpResponseForbidden

class OwnerOnlyAccessMiddleware:
    """
    Enforces a strict single-owner policy (FR-SEC-003).
    Only the superuser account is allowed access. All other requests are
    denied (403) or redirected to the login page.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Allow static files through immediately
        if request.path.startswith(settings.STATIC_URL):
            return self.get_response(request)

        # Allow resolved view checks
        try:
            resolver_match = resolve(request.path)
            view_name = resolver_match.view_name
        except Resolver404:
            view_name = None

        # Exclude login, admin login, and password reset views from redirect checks
        exempt_view_names = [
            'login', 'admin:login', 'logout', 'admin:logout',
            'password_reset', 'password_reset_done', 'password_reset_confirm', 'password_reset_complete'
        ]
        exempt_paths = [
            '/login/', '/admin/login/', '/logout/',
            '/password-reset/', '/password-reset/done/', '/password-reset-complete/'
        ]

        is_exempt = (
            view_name in exempt_view_names or 
            request.path in exempt_paths or 
            request.path.startswith('/admin/')
        )

        if is_exempt:
            return self.get_response(request)

        # If user is not authenticated, redirect to login
        if not request.user.is_authenticated:
            return redirect(settings.LOGIN_URL)

        # Reject authenticated non-owner users (only superusers are owners in V1)
        if not request.user.is_superuser:
            return HttpResponseForbidden("Forbidden: You are not authorized to access this LifeOS.")

        # Activate user local timezone dynamically
        from django.utils import timezone
        import zoneinfo
        from .models import AppSettings
        try:
            app_settings = AppSettings.get_solo()
            if app_settings.timezone:
                timezone.activate(zoneinfo.ZoneInfo(app_settings.timezone))
        except Exception:
            pass

        return self.get_response(request)
