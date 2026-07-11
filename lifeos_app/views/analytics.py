# ==============================================================================
# File: lifeos_app/views/analytics.py
# Description: Velocity Deep Dive surface (P4-SURF-ANALYTICS)
# Component: Surfaces / Analytics
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Stability history, completions vs target, and focus rollups — not on Home."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from lifeos_app.services.analytics import build_analytics_page, parse_window_days


@login_required
def analytics_view(request):
    """Render Analytics history for the selected day window."""
    days = parse_window_days(request.GET.get("days"))
    return render(request, "surfaces/analytics.html", build_analytics_page(days=days))
