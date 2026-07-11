# ==============================================================================
# File: lifeos_app/views/home.py
# Description: Cockpit Home surface and HTMX fragments
# Component: Surfaces / Home
# Version: 2.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Cockpit Home — calm four-bento canvas with P1 live focus + horizon."""

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from lifeos_app.models import (
    ExecutionItem,
    FocusSession,
    ScheduledAllocation,
    StabilitySnapshot,
    SystemEnums,
    WorkspaceContainer,
)
from lifeos_app.services.focus import focus_elapsed_display, get_open_session


def home_context(*, recompute_stability: bool = True) -> dict:
    """Shared context for home and HTMX fragments."""
    open_session = get_open_session()
    active_item = open_session.execution_item if open_session else None

    now = timezone.now()
    horizon_items = list(
        ExecutionItem.objects.filter(is_deleted=False)
        .exclude(status=SystemEnums.ItemStatus.COMPLETED)
        .filter(
            Q(due_at__gte=now)
            | Q(allocation__start_at__gte=now)
            | Q(container_links__container__slug="today")
        )
        .distinct()
        .order_by("due_at", "allocation__start_at")[:3]
    )

    if recompute_stability:
        from lifeos_app.services.stability import ensure_today_stability

        stability = ensure_today_stability()
    else:
        stability = StabilitySnapshot.objects.order_by("-date").first()
    inbox_count = ExecutionItem.objects.filter(
        status=SystemEnums.ItemStatus.INBOX, is_deleted=False
    ).count()
    wip_count = ExecutionItem.objects.filter(
        status=SystemEnums.ItemStatus.IN_PROGRESS, is_deleted=False
    ).count()

    return {
        "active_item": active_item,
        "open_session": open_session,
        "focus_elapsed": focus_elapsed_display(open_session),
        "horizon_items": horizon_items,
        "stability": stability,
        "inbox_count": inbox_count,
        "wip_count": wip_count,
        "system_lists": WorkspaceContainer.objects.filter(
            slug__in=["inbox", "today", "this-week"]
        ).order_by("slug"),
        "upcoming_allocations": ScheduledAllocation.objects.filter(start_at__gte=now)
        .select_related("execution_item")
        .order_by("start_at")[:3],
    }


@login_required
def home_view(request):
    """Render the persistent cockpit home with Active Focus + horizon widgets."""
    ctx = home_context()
    ctx["surface"] = "home"
    return render(request, "surfaces/home.html", ctx)


@login_required
def fragment_active_focus(request):
    """HTMX partial for Tier 1 Active Focus."""
    return render(request, "partials/active_focus.html", home_context())


@login_required
def fragment_horizon(request):
    """HTMX partial for Tier 2 Horizon Feed."""
    return render(request, "partials/horizon_feed.html", home_context())
