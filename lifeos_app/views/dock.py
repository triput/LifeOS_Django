# ==============================================================================
# File: lifeos_app/views/dock.py
# Description: Dock restore endpoints (FR-UI-004)
# Component: Surfaces / Dock
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Bottom dock — restore minimized drawer contexts from session."""

import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_POST

from lifeos_app.services.dock import dock_list, dock_pop


@login_required
def dock_bar_view(request):
    """HTMX partial for footer dock chips."""
    return render(request, "partials/dock_bar.html", {"dock_entries": dock_list(request)})


@login_required
@require_POST
def dock_restore_view(request, token: str):
    """Restore a minimized drawer from the dock."""
    entry = dock_pop(request, token)
    if not entry:
        return render(request, "partials/dock_bar.html", {"dock_entries": dock_list(request)}, status=404)

    if entry["kind"] == "container":
        from lifeos_app.views.drawer import drawer_container_view

        response = drawer_container_view(request, entry["id"])
    else:
        from lifeos_app.views.drawer import drawer_item_view

        response = drawer_item_view(request, entry["id"])

    response["HX-Trigger"] = json.dumps({"drawer-open": True})
    dock_bar = render(request, "partials/dock_bar.html", {"dock_entries": dock_list(request)})
    response.content = (
        response.content
        + b'<div id="dock-bar" hx-swap-oob="innerHTML">'
        + dock_bar.content
        + b"</div>"
    )
    return response
