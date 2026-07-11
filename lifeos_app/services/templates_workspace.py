# ==============================================================================
# File: lifeos_app/services/templates_workspace.py
# Description: Curated workspace template apply (ENG-TEMPLATE / FR-TMPL-001)
# Component: Services / Templates
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Clone curated WorkspaceTemplate trees into live containers and items."""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from django.utils.text import slugify

from lifeos_app.models import (
    ExecutionItem,
    ItemContainerLink,
    SystemEnums,
    WorkspaceContainer,
    WorkspaceTemplate,
    WorkspaceTemplateNode,
)


@dataclass
class TemplatePreview:
    """Palette / Settings preview of a curated template."""

    ok: bool
    slug: str = ""
    title: str = ""
    description: str = ""
    container_count: int = 0
    item_count: int = 0
    message: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "container_count": self.container_count,
            "item_count": self.item_count,
            "message": self.message,
            "warnings": self.warnings,
        }


@dataclass
class TemplateApplyResult:
    """Outcome of ``template apply``."""

    ok: bool
    message: str = ""
    root_container_id: int | None = None
    root_slug: str = ""
    containers_created: int = 0
    items_created: int = 0


def list_active_templates() -> list[WorkspaceTemplate]:
    """Active curated templates for Settings (read-only catalog)."""
    return list(
        WorkspaceTemplate.objects.filter(is_active=True)
        .select_related("domain_hint")
        .prefetch_related("nodes")
        .order_by("title")
    )


def get_template(slug: str) -> WorkspaceTemplate | None:
    """Lookup active template by slug."""
    key = (slug or "").strip().lower()
    if not key:
        return None
    return (
        WorkspaceTemplate.objects.filter(slug__iexact=key, is_active=True)
        .prefetch_related("nodes")
        .first()
    )


def preview_template(slug: str) -> TemplatePreview:
    """Count containers/items that would be created (FR-UI-042)."""
    tmpl = get_template(slug)
    if not tmpl:
        return TemplatePreview(
            ok=False,
            slug=(slug or "").strip(),
            message=f"Unknown template: {slug or '(empty)'}",
            warnings=[f"No active template with slug {(slug or '').strip()!r}."],
        )
    nodes = list(tmpl.nodes.all())
    containers = sum(1 for n in nodes if n.node_kind == "container")
    items = sum(1 for n in nodes if n.node_kind == "item")
    return TemplatePreview(
        ok=True,
        slug=tmpl.slug,
        title=tmpl.title,
        description=tmpl.description,
        container_count=containers,
        item_count=items,
        message=f"Apply “{tmpl.title}” → {containers} container(s), {items} item(s)",
    )


def _ordered_nodes(nodes: list[WorkspaceTemplateNode]) -> list[WorkspaceTemplateNode]:
    """Parents before children (stable for apply)."""
    by_id = {n.pk: n for n in nodes}
    done: set[int] = set()
    ordered: list[WorkspaceTemplateNode] = []

    def visit(node: WorkspaceTemplateNode) -> None:
        if node.pk in done:
            return
        if node.parent_id and node.parent_id in by_id:
            visit(by_id[node.parent_id])
        ordered.append(node)
        done.add(node.pk)

    for node in sorted(nodes, key=lambda n: (n.order, n.pk)):
        visit(node)
    return ordered


def _unique_container_slug(title: str) -> str:
    base = slugify(title) or "container"
    candidate = base
    n = 2
    while WorkspaceContainer.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


@transaction.atomic
def apply_template(slug: str) -> TemplateApplyResult:
    """Clone template tree into live WorkspaceContainer / ExecutionItem rows."""
    tmpl = get_template(slug)
    if not tmpl:
        return TemplateApplyResult(
            ok=False,
            message=f"Unknown template: {slug or '(empty)'}",
        )

    nodes = _ordered_nodes(list(tmpl.nodes.select_related("parent").all()))
    if not nodes:
        return TemplateApplyResult(ok=False, message=f"Template “{tmpl.title}” has no nodes.")

    container_map: dict[int, WorkspaceContainer] = {}
    items_created = 0
    root: WorkspaceContainer | None = None

    para = tmpl.para_hint or SystemEnums.PARACategory.PROJECT
    domain = tmpl.domain_hint

    for node in nodes:
        parent_container = None
        if node.parent_id:
            parent_container = container_map.get(node.parent_id)
            if parent_container is None:
                # Parent was an item or missing — skip with soft continue
                continue

        if node.node_kind == "container":
            ctype = node.container_type or SystemEnums.ContainerType.PROJECT
            container = WorkspaceContainer(
                title=node.title,
                slug=_unique_container_slug(node.title),
                container_type=ctype,
                para_state=para,
                domain=domain,
                parent=parent_container,
                order=node.order,
            )
            container.save()
            container_map[node.pk] = container
            if root is None and parent_container is None:
                root = container
            continue

        if node.node_kind == "item":
            if parent_container is None:
                continue
            item = ExecutionItem.objects.create(
                title=node.title,
                item_type=node.item_type or SystemEnums.ItemType.TASK,
                status=SystemEnums.ItemStatus.BACKLOG,
                estimated_minutes=node.estimated_minutes or 30,
                stack_rank=node.order,
            )
            ItemContainerLink.objects.create(
                item=item,
                container=parent_container,
                is_primary=True,
            )
            items_created += 1

    if root is None and container_map:
        # Prefer a top-level container (no parent) if root detection missed.
        root = next(
            (c for c in container_map.values() if c.parent_id is None),
            next(iter(container_map.values())),
        )

    return TemplateApplyResult(
        ok=True,
        message=(
            f"Applied “{tmpl.title}”: {len(container_map)} container(s), "
            f"{items_created} item(s)"
            + (f" → #{root.slug}" if root else "")
        ),
        root_container_id=root.pk if root else None,
        root_slug=root.slug if root else "",
        containers_created=len(container_map),
        items_created=items_created,
    )
