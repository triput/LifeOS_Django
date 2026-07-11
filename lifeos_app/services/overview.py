# ==============================================================================
# File: lifeos_app/services/overview.py
# Description: Horizon Overview active-leaf aggregator (P4-SURF-OVERVIEW)
# Component: Services / Overview
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Flat cross-container active-leaf queries for SURF-OVERVIEW (FR-UI-033–036)."""

from __future__ import annotations

from dataclasses import dataclass

from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Prefetch, QuerySet

from lifeos_app.models import ExecutionItem, ItemContainerLink, SystemEnums
from lifeos_app.services.matrix import MatrixFacets, apply_item_facets, facet_context

OVERVIEW_PAGE_SIZE = 50

GROUP_BY_URGENCY = "urgency"
GROUP_BY_DOMAIN = "domain"
GROUP_BY_PARA = "para"
GROUP_BY_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "None"),
    (GROUP_BY_URGENCY, "Urgency"),
    (GROUP_BY_DOMAIN, "Domain"),
    (GROUP_BY_PARA, "PARA"),
)

# Display order for urgency groups (IMMEDIATE first).
_URGENCY_ORDER = {
    SystemEnums.UrgencyLevel.IMMEDIATE: 0,
    SystemEnums.UrgencyLevel.HIGH: 1,
    SystemEnums.UrgencyLevel.NORMAL: 2,
    SystemEnums.UrgencyLevel.LOW: 3,
}


@dataclass
class OverviewFacets(MatrixFacets):
    """Matrix facets plus Overview group-by and archive visibility."""

    group_by: str = ""
    include_archived: bool = False
    page: int = 1

    @classmethod
    def from_request(cls, request) -> "OverviewFacets":
        g = request.GET
        base = MatrixFacets.from_request(request)
        group_by = (g.get("group_by") or "").strip().lower()
        if group_by not in {c[0] for c in GROUP_BY_CHOICES}:
            group_by = ""
        try:
            page = max(1, int(g.get("page") or "1"))
        except ValueError:
            page = 1
        return cls(
            q=base.q,
            status=base.status,
            domain=base.domain,
            para=base.para,
            tag=base.tag,
            show_completed=base.show_completed,
            group_by=group_by,
            include_archived=g.get("include_archived") in ("1", "true", "on"),
            page=page,
        )

    def query_string(self, **overrides) -> str:
        data = {
            "q": self.q,
            "status": self.status,
            "domain": self.domain,
            "para": self.para,
            "tag": self.tag,
            "show_completed": "1" if self.show_completed else "",
            "group_by": self.group_by,
            "include_archived": "1" if self.include_archived else "",
            "page": str(self.page) if self.page > 1 else "",
        }
        data.update(overrides)
        return "&".join(f"{k}={v}" for k, v in data.items() if v)


@dataclass
class OverviewGroup:
    """One labeled bucket of leaves for the Overview list."""

    key: str
    label: str
    items: list


def active_leaves(facets: OverviewFacets | MatrixFacets) -> QuerySet:
    """
    Distinct top-level (non-subtask) items across containers.

    Default: exclude COMPLETED (via facets) and items whose primary home is archived.
    """
    include_archived = getattr(facets, "include_archived", False)
    qs = (
        ExecutionItem.objects.filter(is_deleted=False, parent_item__isnull=True)
        .prefetch_related(
            "tags",
            Prefetch(
                "container_links",
                queryset=ItemContainerLink.objects.select_related("container__domain"),
            ),
        )
    )
    if not include_archived:
        archived_primary = ItemContainerLink.objects.filter(
            item_id=OuterRef("pk"),
            is_primary=True,
            container__is_archived=True,
        )
        qs = qs.exclude(Exists(archived_primary))
    return apply_item_facets(qs, facets).order_by(
        "stack_rank", "-priority", "due_at", "title"
    )


def _group_key_label(item: ExecutionItem, group_by: str) -> tuple[str, str, int]:
    """Return (key, label, sort_index) for an item under the active group-by."""
    primary = item.primary_container()
    if group_by == GROUP_BY_URGENCY:
        key = item.urgency or SystemEnums.UrgencyLevel.NORMAL
        label = item.get_urgency_display()
        return key, label, _URGENCY_ORDER.get(key, 99)
    if group_by == GROUP_BY_DOMAIN:
        if primary and primary.domain_id:
            return (
                primary.domain.slug,
                primary.domain.name,
                0,
            )
        return ("_none", "No domain", 99)
    if group_by == GROUP_BY_PARA:
        if primary:
            return (
                primary.para_state,
                primary.get_para_state_display(),
                0,
            )
        return ("_none", "No container", 99)
    return ("_all", "All", 0)


def build_overview_page(facets: OverviewFacets) -> dict:
    """Paginated leaves + optional group buckets for the Overview template."""
    qs = active_leaves(facets)
    paginator = Paginator(qs, OVERVIEW_PAGE_SIZE)
    page_obj = paginator.get_page(facets.page)
    items = list(page_obj.object_list)

    groups: list[OverviewGroup] = []
    if facets.group_by:
        buckets: dict[str, OverviewGroup] = {}
        order: list[tuple[int, str]] = []
        for item in items:
            key, label, sort_idx = _group_key_label(item, facets.group_by)
            if key not in buckets:
                buckets[key] = OverviewGroup(key=key, label=label, items=[])
                order.append((sort_idx, key))
            buckets[key].items.append(item)
        # Stable: sort by sort_idx then label
        order.sort(key=lambda pair: (pair[0], buckets[pair[1]].label.casefold()))
        # Deduplicate keys while preserving order
        seen: set[str] = set()
        for _, key in order:
            if key in seen:
                continue
            seen.add(key)
            groups.append(buckets[key])
    else:
        groups = [OverviewGroup(key="_all", label="", items=items)]

    ctx = facet_context(facets)
    ctx.update(
        {
            "surface": "overview",
            "overview_facets": facets,
            "facets": facets,
            "page_obj": page_obj,
            "groups": groups,
            "item_count": paginator.count,
            "group_by_choices": GROUP_BY_CHOICES,
            "page_size": OVERVIEW_PAGE_SIZE,
            "prev_qs": (
                facets.query_string(page=page_obj.previous_page_number)
                if page_obj.has_previous
                else ""
            ),
            "next_qs": (
                facets.query_string(page=page_obj.next_page_number) if page_obj.has_next else ""
            ),
        }
    )
    return ctx
