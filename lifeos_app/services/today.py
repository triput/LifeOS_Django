# ==============================================================================
# File: lifeos_app/services/today.py
# Description: Plan Today ritual — multi-home onto #today (ENG-TODAY)
# Component: Services / Today
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Plan Today / clear today without changing primary container homes."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from lifeos_app.models import ExecutionItem, ItemContainerLink, SystemEnums, WorkspaceContainer


@dataclass
class TodayResult:
    """Outcome of plan/clear today operations."""

    ok: bool
    count: int = 0
    message: str = ""


def get_today_container() -> WorkspaceContainer | None:
    """Return the system #today list container."""
    return WorkspaceContainer.objects.filter(slug="today").first()


def today_item_ids() -> set[int]:
    """Item IDs currently linked to #today."""
    container = get_today_container()
    if not container:
        return set()
    return set(
        ItemContainerLink.objects.filter(container=container).values_list("item_id", flat=True)
    )


def _active_items_qs():
    return ExecutionItem.objects.filter(is_deleted=False).exclude(
        status=SystemEnums.ItemStatus.COMPLETED
    )


@transaction.atomic
def plan_today(
    item_ids: list[int] | None = None,
    query: str = "",
    limit: int = 12,
) -> TodayResult:
    """
    Multi-home items onto #today without changing primary links.

    When item_ids is omitted, selects active items by optional title query
    or top priority/urgency candidates not already on #today.
    """
    container = get_today_container()
    if not container:
        return TodayResult(ok=False, message="#today container missing.")

    if item_ids:
        items = list(_active_items_qs().filter(pk__in=item_ids))
    elif query.strip():
        items = list(
            _active_items_qs()
            .filter(title__icontains=query.strip())
            .order_by("priority", "due_at", "title")[:limit]
        )
    else:
        already = today_item_ids()
        items = list(
            _active_items_qs()
            .exclude(pk__in=already)
            .order_by("priority", "due_at", "title")[:limit]
        )

    added = 0
    for item in items:
        link, created = ItemContainerLink.objects.get_or_create(
            item=item,
            container=container,
            defaults={"is_primary": False, "pinned": False},
        )
        if created:
            added += 1
        elif link.is_primary:
            # Never demote primary — skip if somehow primary is today (invalid seed edge)
            continue

    return TodayResult(
        ok=True,
        count=added,
        message=f"Added {added} item(s) to #today." if added else "No new items added to #today.",
    )


@transaction.atomic
def clear_today() -> TodayResult:
    """Remove all non-primary #today links only."""
    container = get_today_container()
    if not container:
        return TodayResult(ok=False, message="#today container missing.")

    deleted, _ = ItemContainerLink.objects.filter(
        container=container,
        is_primary=False,
    ).delete()
    return TodayResult(
        ok=True,
        count=deleted,
        message=f"Cleared {deleted} item(s) from #today.",
    )


def today_items():
    """Active items linked to #today for Planner/Horizon."""
    container = get_today_container()
    if not container:
        return ExecutionItem.objects.none()
    return (
        _active_items_qs()
        .filter(container_links__container=container)
        .prefetch_related("tags", "container_links__container", "allocation")
        .distinct()
        .order_by("priority", "due_at", "title")
    )
