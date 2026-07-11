# ==============================================================================
# File: lifeos_app/views/telemetry.py
# Description: Lazy Tier 4 telemetry HUD (ENG-TELE)
# Component: Surfaces / Home
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""HTMX endpoint for Home Tier 4 weather and space weather."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from lifeos_app.services.telemetry import build_telemetry_hud


@login_required
@require_GET
def telemetry_hud_view(request):
    """Lazy-load terrestrial + space weather for the Home telemetry card."""
    return render(request, "partials/telemetry_hud.html", build_telemetry_hud())
