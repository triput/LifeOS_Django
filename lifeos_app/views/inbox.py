# ==============================================================================
# File: lifeos_app/views/inbox.py
# Description: Inbox triage surface (ENG-TRIAGE)
# Component: Surfaces / Inbox
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Inbox triage — review orphans and assign to containers."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_POST

from lifeos_app.models import WorkspaceContainer
from lifeos_app.services.triage import inbox_queryset, structural_orphans, triage_item


@login_required
def inbox_view(request):
    """Render inbox triage surface."""
    containers = WorkspaceContainer.objects.filter(is_archived=False).order_by("title")
    return render(
        request,
        "surfaces/inbox.html",
        {
            "surface": "inbox",
            "inbox_items": inbox_queryset(),
            "orphan_containers": structural_orphans(),
            "containers": containers,
        },
    )


@login_required
@require_POST
def inbox_triage_view(request, item_id: int):
    """Process a single inbox item to a target container."""
    from lifeos_app.models import ExecutionItem

    item = ExecutionItem.objects.filter(pk=item_id, is_deleted=False).first()
    if not item:
        return render(request, "partials/inbox_row.html", {"error": "Item not found."}, status=404)

    container_slug = request.POST.get("container_slug", "").strip().lstrip("#")
    tag_raw = request.POST.get("tags", "")
    tag_slugs = [t.strip().lstrip("@") for t in tag_raw.split() if t.strip()]

    result = triage_item(item, container_slug, tag_slugs or None)
    if not result.ok:
        return render(
            request,
            "partials/inbox_row.html",
            {"item": item, "containers": WorkspaceContainer.objects.filter(is_archived=False), "error": result.message},
            status=422,
        )

    # Row removed on success — empty response for hx-swap outerHTML
    return render(request, "partials/inbox_row_removed.html", {"message": result.message})
