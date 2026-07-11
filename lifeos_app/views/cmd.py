# ==============================================================================
# File: lifeos_app/views/cmd.py
# Description: Cmd+K palette preview and commit endpoints
# Component: Surfaces / Command Palette
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""HTMX endpoints for Lightning Capture and palette commands."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from lifeos_app.services.cmd import commit_command, preview_command
from lifeos_app.views.htmx import set_cockpit_refresh, set_hx_trigger


@login_required
@require_POST
def cmd_preview_view(request):
    """Debounced palette preview partial."""
    raw = request.POST.get("input", "")
    preview = preview_command(raw)
    return render(
        request,
        "partials/palette_preview.html",
        {"preview": preview},
    )


@login_required
@require_POST
def cmd_commit_view(request):
    """Execute palette command; redirect or refresh home fragments."""
    raw = request.POST.get("input", "")
    selected_item_id = request.POST.get("item_id")
    item_id = int(selected_item_id) if selected_item_id and selected_item_id.isdigit() else None
    result = commit_command(
        raw,
        selected_item_id=item_id,
        view_surface=request.POST.get("view_surface", ""),
        view_query_string=request.POST.get("view_query_string", ""),
    )

    if result.redirect_url:
        response = HttpResponse(status=204)
        response["HX-Redirect"] = result.redirect_url
        return response

    if not result.ok:
        preview = preview_command(raw)
        response = render(
            request,
            "partials/palette_preview.html",
            {"preview": preview, "error": result.message},
        )
        response.status_code = 422
        return response

    # Successful save view — close palette (facets already captured from hidden fields)
    if raw.strip().lower().startswith("save view"):
        response = HttpResponse(status=204)
        set_hx_trigger(response, "palette-close")
        return response

    response = HttpResponse(status=204)
    if result.refresh_fragments:
        set_cockpit_refresh(response, **{"palette-close": True})
    return response
