# ==============================================================================
# File: lifeos_app/views/drawer.py
# Description: Detail drawer fragments for items and containers (FR-UI-003)
# Component: Surfaces / Drawer
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Right-hand detail drawer — items, containers, and calendar events."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from lifeos_app.models import ExecutionItem, SystemEnums, WorkspaceContainer
from lifeos_app.services.dock import dock_list, dock_minimize


def _due_at_local_value(item: ExecutionItem) -> str:
    """Format due_at for datetime-local input in the active timezone."""
    if not item.due_at:
        return ""
    local = timezone.localtime(item.due_at)
    return local.strftime("%Y-%m-%dT%H:%M")


def item_drawer_context(item: ExecutionItem, *, error: str = "", notice: str = "") -> dict:
    """Shared context for item drawer GET and post-patch refresh."""
    from lifeos_app.services.manual_time import item_spent_breakdown

    blocked_deps = item.dependency_links_out.filter(
        link_type=SystemEnums.DependencyLinkType.BLOCKS,
        to_item__is_deleted=False,
    ).exclude(to_item__status=SystemEnums.ItemStatus.COMPLETED).select_related("to_item")
    return {
        "item": item,
        "blocked_deps": blocked_deps,
        "drawer_error": error,
        "drawer_notice": notice,
        "spent": item_spent_breakdown(item),
        "status_choices": SystemEnums.ItemStatus.choices,
        "priority_choices": SystemEnums.PriorityLevel.choices,
        "urgency_choices": SystemEnums.UrgencyLevel.choices,
        "due_at_local": _due_at_local_value(item),
    }


def container_drawer_context(
    container: WorkspaceContainer, *, error: str = "", notice: str = ""
) -> dict:
    """Shared context for container drawer GET and post-patch refresh."""
    from lifeos_app.services.academy import is_academy_surface
    from lifeos_app.services.manual_time import container_spent_breakdown

    item_count = container.execution_items.filter(is_deleted=False).count()
    return {
        "container": container,
        "item_count": item_count,
        "show_academy_fields": is_academy_surface(container),
        "drawer_error": error,
        "drawer_notice": notice,
        "spent": container_spent_breakdown(container),
        "para_choices": SystemEnums.PARACategory.choices,
        "priority_choices": SystemEnums.PriorityLevel.choices,
        "urgency_choices": SystemEnums.UrgencyLevel.choices,
    }


def render_item_drawer(
    request, item: ExecutionItem, *, error: str = "", notice: str = "", status: int = 200
):
    """Render item drawer fragment (optionally with a save error)."""
    response = render(
        request,
        "partials/drawer_item.html",
        item_drawer_context(item, error=error, notice=notice),
        status=status,
    )
    if request.htmx and not error:
        response["HX-Trigger"] = "drawer-open"
    return response


def render_container_drawer(
    request,
    container: WorkspaceContainer,
    *,
    error: str = "",
    notice: str = "",
    status: int = 200,
):
    """Render container drawer fragment (optionally with a save error)."""
    response = render(
        request,
        "partials/drawer_container.html",
        container_drawer_context(container, error=error, notice=notice),
        status=status,
    )
    if request.htmx and not error:
        response["HX-Trigger"] = "drawer-open"
    return response


@login_required
def drawer_item_view(request, item_id: int):
    """Render item detail drawer."""
    item = get_object_or_404(
        ExecutionItem.objects.prefetch_related(
            "tags", "container_links__container", "dependency_links_out__to_item"
        ),
        pk=item_id,
        is_deleted=False,
    )
    return render_item_drawer(request, item)


@login_required
def drawer_calendar_event_view(request, event_id: int):
    """Read-only detail for a synced external calendar event (BL-CAL-003)."""
    from lifeos_app.models import CalendarEvent

    event = get_object_or_404(
        CalendarEvent.objects.select_related("source_calendar", "integration"),
        pk=event_id,
    )
    response = render(
        request,
        "partials/drawer_calendar_event.html",
        {"event": event},
    )
    if request.htmx:
        response["HX-Trigger"] = "drawer-open"
    return response


@login_required
def drawer_container_view(request, container_id: int):
    """Render container detail drawer."""
    container = get_object_or_404(
        WorkspaceContainer.objects.select_related("domain", "parent", "certification"),
        pk=container_id,
    )
    return render_container_drawer(request, container)


@login_required
@require_POST
def drawer_minimize_view(request):
    """Minimize open drawer to session dock."""
    kind = request.POST.get("kind", "item")
    obj_id = int(request.POST.get("id", 0))
    label = request.POST.get("label", "Untitled")
    if not obj_id:
        return render(request, "partials/dock_bar.html", {"dock_entries": []}, status=400)
    dock_minimize(request, kind, obj_id, label)
    response = render(request, "partials/dock_bar.html", {"dock_entries": dock_list(request)})
    response["HX-Trigger"] = "drawer-close"
    return response


@login_required
@require_POST
def item_add_time_view(request, item_id: int):
    """Add manual time on an item (BL-TIME-004)."""
    from lifeos_app.services.manual_time import add_time_to_item

    item = get_object_or_404(ExecutionItem, pk=item_id, is_deleted=False)
    result = add_time_to_item(
        item,
        request.POST.get("duration", ""),
        note=request.POST.get("note", ""),
    )
    item.refresh_from_db()
    if not result.ok:
        return render_item_drawer(request, item, error=result.message, status=422)
    return render_item_drawer(request, item, notice=result.message)


@login_required
@require_POST
def container_add_time_view(request, container_id: int):
    """Add manual time on a container (BL-TIME-004)."""
    from lifeos_app.services.manual_time import add_time_to_container

    container = get_object_or_404(WorkspaceContainer, pk=container_id)
    result = add_time_to_container(
        container,
        request.POST.get("duration", ""),
        note=request.POST.get("note", ""),
    )
    container.refresh_from_db()
    if not result.ok:
        return render_container_drawer(request, container, error=result.message, status=422)
    return render_container_drawer(request, container, notice=result.message)
