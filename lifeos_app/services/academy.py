# ==============================================================================
# File: lifeos_app/services/academy.py
# Description: Academy Hub cert progress + course tree rollups (P4-SURF-ACADEMY)
# Component: Services / Academy
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Certification meters and recursive course/specialization completion (FR-UI-014–016)."""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q, Sum

from lifeos_app.models import (
    Certification,
    DomainCategory,
    ExecutionItem,
    ItemContainerLink,
    SystemEnums,
    WorkspaceContainer,
)

ACADEMY_TYPES = frozenset(
    {
        SystemEnums.ContainerType.SPECIALIZATION,
        SystemEnums.ContainerType.COURSE,
        SystemEnums.ContainerType.MODULE,
    }
)


@dataclass
class CertProgress:
    """Completed vs required credits for one Certification."""

    certification: Certification
    credits_earned: float
    credits_required: float
    unit: str
    percent: int  # 0–100 capped for meter
    container_count: int

    @property
    def is_complete(self) -> bool:
        return self.credits_required > 0 and self.credits_earned >= self.credits_required


@dataclass
class CourseNode:
    """Academy container with recursive completion + child tree."""

    container: WorkspaceContainer
    item_total: int
    item_completed: int
    percent: int
    credits_earned: float
    children: list[CourseNode] = field(default_factory=list)

    @property
    def show_academy_fields(self) -> bool:
        """FR-UI-015 — academy attrs when domain flag or academy container type."""
        return is_academy_surface(self.container)


def is_academy_surface(container: WorkspaceContainer) -> bool:
    """True when Academy-specific fields should render."""
    if container.container_type in ACADEMY_TYPES:
        return True
    domain = container.domain
    return bool(domain and domain.is_academy)


def _descendant_container_ids(root: WorkspaceContainer) -> set[int]:
    """BFS of container subtree including root."""
    ids = {root.pk}
    frontier = [root.pk]
    while frontier:
        kids = list(
            WorkspaceContainer.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
        )
        frontier = [k for k in kids if k not in ids]
        ids.update(frontier)
    return ids


def item_progress_for_containers(container_ids: set[int]) -> tuple[int, int]:
    """
    Count distinct non-deleted items primarily homed under any of container_ids.

    Returns (completed, total).
    """
    if not container_ids:
        return 0, 0
    item_ids = (
        ItemContainerLink.objects.filter(
            container_id__in=container_ids,
            is_primary=True,
            item__is_deleted=False,
        )
        .values_list("item_id", flat=True)
        .distinct()
    )
    qs = ExecutionItem.objects.filter(pk__in=item_ids)
    total = qs.count()
    completed = qs.filter(status=SystemEnums.ItemStatus.COMPLETED).count()
    return completed, total


def completion_percent(completed: int, total: int) -> int:
    """0–100 completion ratio; empty tree → 0."""
    if total <= 0:
        return 0
    return max(0, min(100, int(round(100.0 * completed / total))))


def build_course_node(container: WorkspaceContainer, child_map: dict[int, list[WorkspaceContainer]]) -> CourseNode:
    """Recursive completion % for a specialization/course/module subtree."""
    subtree_ids = _descendant_container_ids(container)
    completed, total = item_progress_for_containers(subtree_ids)
    children = [
        build_course_node(child, child_map)
        for child in child_map.get(container.pk, [])
    ]
    return CourseNode(
        container=container,
        item_total=total,
        item_completed=completed,
        percent=completion_percent(completed, total),
        credits_earned=float(container.credits_earned or 0),
        children=children,
    )


def academy_containers_queryset():
    """Non-archived containers in academy domains or academy types."""
    return (
        WorkspaceContainer.objects.filter(is_archived=False)
        .filter(
            Q(domain__is_academy=True)
            | Q(container_type__in=list(ACADEMY_TYPES))
        )
        .select_related("domain", "certification", "parent")
        .order_by("order", "title")
    )


def build_cert_progress() -> list[CertProgress]:
    """FR-UI-014 — credits earned (sum of linked containers) vs required."""
    rows: list[CertProgress] = []
    for cert in Certification.objects.order_by("name"):
        linked = WorkspaceContainer.objects.filter(
            certification=cert,
            is_archived=False,
        )
        agg = linked.aggregate(total=Sum("credits_earned"))
        earned = float(agg["total"] or 0)
        required = float(cert.credits_required or 0)
        pct = 0
        if required > 0:
            pct = max(0, min(100, int(round(100.0 * earned / required))))
        elif earned > 0:
            pct = 100
        rows.append(
            CertProgress(
                certification=cert,
                credits_earned=earned,
                credits_required=required,
                unit=cert.credit_unit_type or "CEU",
                percent=pct,
                container_count=linked.count(),
            )
        )
    return rows


def build_course_forest() -> list[CourseNode]:
    """Top-level academy trees (no parent, or parent outside academy set)."""
    containers = list(academy_containers_queryset())
    by_id = {c.pk: c for c in containers}
    child_map: dict[int, list[WorkspaceContainer]] = {}
    for c in containers:
        if c.parent_id and c.parent_id in by_id:
            child_map.setdefault(c.parent_id, []).append(c)

    roots = [
        c
        for c in containers
        if not c.parent_id or c.parent_id not in by_id
    ]
    # Prefer specialization/course roots first
    type_rank = {
        SystemEnums.ContainerType.SPECIALIZATION: 0,
        SystemEnums.ContainerType.COURSE: 1,
        SystemEnums.ContainerType.MODULE: 2,
    }
    roots.sort(key=lambda c: (type_rank.get(c.container_type, 9), c.order, c.title))
    return [build_course_node(root, child_map) for root in roots]


def build_academy_page() -> dict:
    """Context for `/canvas/academy/`."""
    certs = build_cert_progress()
    forest = build_course_forest()
    academy_domains = DomainCategory.objects.filter(is_academy=True, is_active=True).order_by("name")
    return {
        "surface": "academy",
        "cert_progress": certs,
        "course_forest": forest,
        "academy_domains": academy_domains,
        "academy_container_count": academy_containers_queryset().count(),
    }
