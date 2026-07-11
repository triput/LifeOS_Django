# ==============================================================================
# File: lifeos_app/views/calendar_grid.py
# Description: Unified calendar grid surface (BL-CAL-002)
# Component: Surfaces / Plan
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Month/week calendar grid with per-source display filters."""

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from lifeos_app.models import SyncedCalendar
from lifeos_app.services.calendar_grid import (
    VIEW_MONTH,
    calendar_grid_context,
    set_calendar_display_enabled,
)


def _parse_anchor(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _show_allocations(request) -> bool:
    """Session-backed allocations layer toggle (default on)."""
    if "show_allocations" in request.GET:
        enabled = request.GET.get("show_allocations", "1") not in {"0", "false", "off"}
        request.session["cal_grid_show_allocations"] = enabled
        return enabled
    return request.session.get("cal_grid_show_allocations", True)


def _grid_context(request) -> dict:
    view = request.POST.get("view") or request.GET.get("view", VIEW_MONTH)
    anchor = _parse_anchor(request.POST.get("day") or request.GET.get("day"))
    return calendar_grid_context(
        view=view,
        anchor=anchor,
        show_allocations=_show_allocations(request),
    )


@login_required
@require_GET
def plan_calendar_view(request):
    """Full-page month/week calendar grid."""
    ctx = _grid_context(request)
    template = "partials/plan_calendar_grid_page.html" if request.htmx else "surfaces/plan_calendar.html"
    return render(request, template, ctx)


@login_required
@require_POST
def plan_calendar_display_toggle_view(request, calendar_pk: int):
    """Toggle display_enabled for one SyncedCalendar (grid only)."""
    synced = SyncedCalendar.objects.filter(pk=calendar_pk).first()
    if not synced:
        return HttpResponseBadRequest("Unknown calendar.")
    enabled = request.POST.get("display_enabled", "").lower() in {"1", "true", "on", "yes"}
    set_calendar_display_enabled(synced, enabled=enabled)
    ctx = _grid_context(request)
    return render(request, "partials/plan_calendar_grid_page.html", ctx)


@login_required
@require_POST
def plan_calendar_allocations_toggle_view(request):
    """Toggle LifeOS allocations layer on the grid."""
    enabled = request.POST.get("show_allocations", "").lower() in {"1", "true", "on", "yes"}
    request.session["cal_grid_show_allocations"] = enabled
    ctx = calendar_grid_context(
        view=request.POST.get("view") or request.GET.get("view", VIEW_MONTH),
        anchor=_parse_anchor(request.POST.get("day") or request.GET.get("day")),
        show_allocations=enabled,
    )
    return render(request, "partials/plan_calendar_grid_page.html", ctx)
