# ==============================================================================
# File: lifeos_app/services/triage.py
# Description: Inbox triage actions (ENG-TRIAGE)
# Component: Services / Triage Engine
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Process inbox orphans — assign containers and advance status."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from lifeos_app.models import (
    ExecutionItem,
    ItemContainerLink,
    SystemEnums,
    WorkspaceContainer,
)
from lifeos_app.services.tags import resolve_tag


@dataclass
class TriageResult:
    ok: bool
    message: str = ""
    item: ExecutionItem | None = None


def inbox_queryset():
    """Items needing triage attention."""
    return (
        ExecutionItem.objects.filter(
            is_deleted=False,
            status=SystemEnums.ItemStatus.INBOX,
        )
        .select_related("allocation")
        .prefetch_related("container_links__container", "tags")
    )


def structural_orphans():
    """Containers missing domain assignment (non-system lists)."""
    return WorkspaceContainer.objects.filter(
        domain__isnull=True,
        is_archived=False,
    ).exclude(slug__in=["inbox", "today", "this-week"])


@transaction.atomic
def triage_item(
    item: ExecutionItem,
    container_slug: str,
    tag_slugs: list[str] | None = None,
) -> TriageResult:
    """Assign primary container and process item out of Inbox."""
    container = WorkspaceContainer.objects.filter(slug=container_slug).first()
    if not container:
        return TriageResult(ok=False, message=f"Unknown container #{container_slug}")

    ItemContainerLink.objects.filter(item=item, is_primary=True).update(is_primary=False)
    link, created = ItemContainerLink.objects.get_or_create(
        item=item,
        container=container,
        defaults={"is_primary": True},
    )
    if not created:
        link.is_primary = True
        link.save(update_fields=["is_primary"])

    if tag_slugs:
        for slug in tag_slugs:
            item.tags.add(resolve_tag(slug))

    if item.due_at or getattr(item, "allocation", None):
        item.status = SystemEnums.ItemStatus.PLANNED
    else:
        item.status = SystemEnums.ItemStatus.BACKLOG
    item.save(update_fields=["status", "updated_at"])

    return TriageResult(ok=True, message=f"Triaged → #{container_slug}", item=item)
