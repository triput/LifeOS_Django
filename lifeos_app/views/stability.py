# ==============================================================================
# File: lifeos_app/views/stability.py
# Description: Stability HUD fragment (P4-ENG-STABILITY)
# Component: Surfaces / Home
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Tier 3 System Stability Index fragment."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from lifeos_app.views.home import home_context


@login_required
def stability_hud_view(request):
    """HTMX partial for Home Tier 3 — recomputes today's snapshot."""
    ctx = home_context(recompute_stability=True)
    return render(request, "partials/stability_hud.html", ctx)
