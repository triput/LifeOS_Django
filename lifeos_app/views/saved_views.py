# ==============================================================================
# File: lifeos_app/views/saved_views.py
# Description: Save / apply SavedView endpoints (P4-ENG-VIEWS)
# Component: Surfaces / Saved Views
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""HTMX save-from-facet-bar and go-view redirect."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from lifeos_app.models import SavedView
from lifeos_app.services.saved_views import (
    build_view_url,
    get_view,
    params_from_query_string,
    save_view,
    views_bar_context,
)


@login_required
@require_POST
def saved_view_save_view(request):
    """Persist current facet query string as a named SavedView."""
    title = request.POST.get("title", "")
    surface = request.POST.get("surface", "")
    query_string = request.POST.get("query_string", "")
    pinned = request.POST.get("is_pinned") in ("1", "true", "on")
    result = save_view(
        title=title,
        target_surface=surface,
        query_params=params_from_query_string(query_string),
        is_pinned=pinned,
    )
    ctx = views_bar_context(
        surface=surface or "matrix",
        message=result.message,
        ok=result.ok,
    )
    # Preserve the query string the owner just saved for the form default.
    ctx["views_query_string"] = query_string
    status = 200 if result.ok else 422
    return render(request, "partials/saved_views_bar.html", ctx, status=status)


@login_required
@require_GET
def saved_view_go_view(request, slug: str):
    """Navigate to a saved view's surface + params (FR-VIEW-001)."""
    view = get_view(slug)
    if view is None:
        view = get_object_or_404(SavedView, slug=slug, is_archived=False)
    url = build_view_url(view)
    if request.htmx:
        response = HttpResponse(status=204)
        response["HX-Redirect"] = url
        return response
    return redirect(url)
