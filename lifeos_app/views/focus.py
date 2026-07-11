# ==============================================================================
# File: lifeos_app/views/focus.py
# Description: Focus Engine HTMX endpoints (ENG-FOCUS)
# Component: Surfaces / Focus
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Start, pause, and complete focus with server-authoritative timing."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from lifeos_app.models import ExecutionItem
from lifeos_app.services.focus import complete_focus, pause_focus, start_focus
from lifeos_app.views.home import home_context
from lifeos_app.views.htmx import set_cockpit_refresh


@login_required
@require_POST
def focus_start_view(request, item_id: int):
    """Start focus on a specific execution item."""
    item = get_object_or_404(ExecutionItem, pk=item_id, is_deleted=False)
    result = start_focus(item)
    if request.htmx:
        if not result.ok:
            response = render(
                request,
                "partials/active_focus.html",
                home_context(),
            )
            response.status_code = 422
            return response
        response = render(request, "partials/active_focus.html", home_context())
        set_cockpit_refresh(response)
        return response
    return HttpResponse(result.message, status=200 if result.ok else 422)


@login_required
@require_POST
def focus_pause_view(request):
    """Pause the globally active focus session."""
    result = pause_focus()
    if request.htmx:
        response = render(request, "partials/active_focus.html", home_context())
        if result.ok:
            set_cockpit_refresh(response)
        else:
            response.status_code = 422
        return response
    return HttpResponse(result.message, status=200 if result.ok else 422)


@login_required
@require_POST
def focus_complete_view(request, item_id: int | None = None):
    """Complete focus — optional explicit item id."""
    item = None
    if item_id is not None:
        item = get_object_or_404(ExecutionItem, pk=item_id, is_deleted=False)
    result = complete_focus(item)
    if request.htmx:
        response = render(request, "partials/active_focus.html", home_context())
        if result.ok:
            set_cockpit_refresh(response)
        else:
            response.status_code = 422
        return response
    return HttpResponse(result.message, status=200 if result.ok else 422)
