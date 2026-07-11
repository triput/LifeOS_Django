# ==============================================================================
# File: lifeos_app/services/matrix.py
# Description: Backlog Matrix tree queries and facet filtering (ENG-MATRIX)
# Component: Services / Matrix
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Matrix surface data — container tree, facets, and lazy child loading."""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count, Q, QuerySet

from lifeos_app.models import DomainCategory, ExecutionItem, SystemEnums, Tag, WorkspaceContainer


@dataclass
class MatrixFacets:
    """Parsed facet query parameters for Matrix / Overview surfaces."""

    q: str = ""
    status: str = ""
    domain: str = ""
    para: str = ""
    tag: str = ""
    show_completed: bool = False

    @classmethod
    def from_request(cls, request) -> "MatrixFacets":
        g = request.GET
        return cls(
            q=(g.get("q") or "").strip(),
            status=(g.get("status") or "").strip(),
            domain=(g.get("domain") or "").strip(),
            para=(g.get("para") or "").strip(),
            tag=(g.get("tag") or "").strip(),
            show_completed=g.get("show_completed") in ("1", "true", "on"),
        )

    def query_string(self, **overrides) -> str:
        data = {
            "q": self.q,
            "status": self.status,
            "domain": self.domain,
            "para": self.para,
            "tag": self.tag,
            "show_completed": "1" if self.show_completed else "",
        }
        data.update(overrides)
        return "&".join(f"{k}={v}" for k, v in data.items() if v)


def apply_item_facets(qs: QuerySet, facets: MatrixFacets) -> QuerySet:
    """Filter execution items by matrix facet params."""
    if not facets.show_completed:
        qs = qs.exclude(status=SystemEnums.ItemStatus.COMPLETED)
    if facets.status:
        statuses = [s.strip().upper() for s in facets.status.split(",") if s.strip()]
        if len(statuses) == 1:
            qs = qs.filter(status=statuses[0])
        elif statuses:
            qs = qs.filter(status__in=statuses)
    if facets.q:
        qs = qs.filter(title__icontains=facets.q)
    if facets.tag:
        qs = qs.filter(tags__name__iexact=facets.tag)
    if facets.domain:
        qs = qs.filter(container_links__container__domain__slug=facets.domain)
    if facets.para:
        qs = qs.filter(container_links__container__para_state=facets.para)
    return qs.distinct()


def root_containers(facets: MatrixFacets) -> QuerySet:
    """Top-level containers for the matrix tree."""
    qs = WorkspaceContainer.objects.filter(parent__isnull=True).select_related("domain")
    if not facets.show_completed:
        qs = qs.filter(is_archived=False)
    if facets.domain:
        qs = qs.filter(domain__slug=facets.domain)
    if facets.para:
        qs = qs.filter(para_state=facets.para)
    if facets.q:
        qs = qs.filter(title__icontains=facets.q)
    return qs.annotate(
        task_count=Count(
            "item_links",
            filter=Q(
                item_links__is_primary=True,
                item_links__item__is_deleted=False,
            ),
            distinct=True,
        ),
        child_count=Count("children", distinct=True),
    ).order_by("order", "title")


def child_containers(parent_id: int, facets: MatrixFacets) -> QuerySet:
    """Nested containers under a parent node."""
    qs = WorkspaceContainer.objects.filter(parent_id=parent_id).select_related("domain")
    if not facets.show_completed:
        qs = qs.filter(is_archived=False)
    if facets.domain:
        qs = qs.filter(domain__slug=facets.domain)
    if facets.para:
        qs = qs.filter(para_state=facets.para)
    return qs.order_by("order", "title")


def container_items(container_id: int, facets: MatrixFacets) -> QuerySet:
    """Execution items primarily homed in a container (top-level leaves only)."""
    qs = (
        ExecutionItem.objects.filter(
            container_links__container_id=container_id,
            container_links__is_primary=True,
            parent_item__isnull=True,
            is_deleted=False,
        )
        .prefetch_related("tags")
        .select_related("parent_item")
    )
    return apply_item_facets(qs, facets).order_by("stack_rank", "-priority", "due_at", "title")


def item_subtasks(parent_id: int, facets: MatrixFacets) -> QuerySet:
    """Subtasks folded under a parent execution item."""
    qs = ExecutionItem.objects.filter(parent_item_id=parent_id, is_deleted=False).prefetch_related("tags")
    return apply_item_facets(qs, facets).order_by("stack_rank", "title")


def facet_context(facets: MatrixFacets) -> dict:
    """Dropdown options for the matrix facet bar."""
    return {
        "facets": facets,
        "domains": DomainCategory.objects.filter(is_active=True).order_by("name"),
        "tags": Tag.objects.order_by("name"),
        "status_choices": SystemEnums.ItemStatus.choices,
        "para_choices": SystemEnums.PARACategory.choices,
    }
