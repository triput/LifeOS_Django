# ==============================================================================
# File: lifeos_app/services/board.py
# Description: Boards Kanban + stack-rank data (P4-SURF-BOARD)
# Component: Services / Board
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Status Kanban columns and priority stack-rank lists for SURF-BOARD."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from lifeos_app.models import ExecutionItem, SystemEnums
from lifeos_app.services.matrix import MatrixFacets, facet_context
from lifeos_app.services.overview import active_leaves
from lifeos_app.services.patch import PatchResult, patch_item_field

MODE_STATUS = "status"
MODE_STACK = "stack"

# Column order for status Kanban (FR-UI-012).
BOARD_STATUSES: tuple[str, ...] = (
    SystemEnums.ItemStatus.INBOX,
    SystemEnums.ItemStatus.BACKLOG,
    SystemEnums.ItemStatus.PLANNED,
    SystemEnums.ItemStatus.IN_PROGRESS,
    SystemEnums.ItemStatus.BLOCKED,
    SystemEnums.ItemStatus.COMPLETED,
)


@dataclass
class BoardFacets(MatrixFacets):
    """Matrix facets plus Board mode (status Kanban vs stack-rank)."""

    mode: str = MODE_STATUS

    @classmethod
    def from_request(cls, request) -> "BoardFacets":
        base = MatrixFacets.from_request(request)
        mode = (request.GET.get("mode") or MODE_STATUS).strip().lower()
        if mode not in (MODE_STATUS, MODE_STACK):
            mode = MODE_STATUS
        return cls(
            q=base.q,
            status=base.status,
            domain=base.domain,
            para=base.para,
            tag=base.tag,
            show_completed=base.show_completed if mode == MODE_STATUS else True,
            mode=mode,
        )

    def query_string(self, **overrides) -> str:
        data = {
            "q": self.q,
            "status": self.status,
            "domain": self.domain,
            "para": self.para,
            "tag": self.tag,
            "show_completed": "1" if self.show_completed else "",
            "mode": self.mode if self.mode != MODE_STATUS else "",
        }
        data.update(overrides)
        return "&".join(f"{k}={v}" for k, v in data.items() if v)


@dataclass
class BoardColumn:
    """One Kanban column."""

    status: str
    label: str
    items: list


def board_items(facets: BoardFacets):
    """Active leaves for the Board, ordered by stack_rank."""
    # Stack mode always shows completed so rank history is visible; status mode
    # respects show_completed like Overview.
    leaf_facets = facets
    if facets.mode == MODE_STACK:
        leaf_facets = BoardFacets(
            q=facets.q,
            status=facets.status,
            domain=facets.domain,
            para=facets.para,
            tag=facets.tag,
            show_completed=True,
            mode=MODE_STACK,
        )
    return active_leaves(leaf_facets)


def build_board_page(facets: BoardFacets) -> dict:
    """Template context for status Kanban or stack-rank mode."""
    items = list(board_items(facets))
    columns: list[BoardColumn] = []
    if facets.mode == MODE_STATUS:
        by_status: dict[str, list] = {s: [] for s in BOARD_STATUSES}
        for item in items:
            if item.status in by_status:
                by_status[item.status].append(item)
            else:
                by_status.setdefault(item.status, []).append(item)
        status_labels = dict(SystemEnums.ItemStatus.choices)
        for status in BOARD_STATUSES:
            columns.append(
                BoardColumn(
                    status=status,
                    label=status_labels.get(status, status),
                    items=by_status.get(status, []),
                )
            )
    ctx = facet_context(facets)
    # Mode toggle query strings (Django templates cannot call query_string with kwargs).
    status_qs = BoardFacets(
        q=facets.q,
        status=facets.status,
        domain=facets.domain,
        para=facets.para,
        tag=facets.tag,
        show_completed=facets.show_completed,
        mode=MODE_STATUS,
    ).query_string()
    stack_qs = BoardFacets(
        q=facets.q,
        status=facets.status,
        domain=facets.domain,
        para=facets.para,
        tag=facets.tag,
        show_completed=True,
        mode=MODE_STACK,
    ).query_string()
    ctx.update(
        {
            "surface": "board",
            "facets": facets,
            "board_mode": facets.mode,
            "columns": columns,
            "stack_items": items if facets.mode == MODE_STACK else [],
            "item_count": len(items),
            "mode_status": MODE_STATUS,
            "mode_stack": MODE_STACK,
            "status_mode_qs": status_qs,
            "stack_mode_qs": stack_qs,
        }
    )
    return ctx


@transaction.atomic
def reorder_items(ordered_ids: list[int]) -> PatchResult:
    """Persist stack_rank from an ordered id list (0..n)."""
    ids = [int(i) for i in ordered_ids if str(i).isdigit() or isinstance(i, int)]
    if not ids:
        return PatchResult(ok=False, message="No items to reorder.")
    existing = set(
        ExecutionItem.objects.filter(pk__in=ids, is_deleted=False).values_list("pk", flat=True)
    )
    ids = [i for i in ids if i in existing]
    for rank, pk in enumerate(ids):
        ExecutionItem.objects.filter(pk=pk).update(stack_rank=rank)
    return PatchResult(ok=True, message=f"Reordered {len(ids)} items.", field="stack_rank")


def move_item_status(item_id: int, new_status: str, ordered_ids: list[int] | None = None) -> PatchResult:
    """Change status (dep-aware) then optionally reorder the destination column."""
    try:
        item = ExecutionItem.objects.get(pk=item_id, is_deleted=False)
    except ExecutionItem.DoesNotExist:
        return PatchResult(ok=False, message="Item not found.")
    result = patch_item_field(item, "status", new_status)
    if not result.ok:
        return result
    if ordered_ids is not None:
        reorder = reorder_items(ordered_ids)
        if not reorder.ok:
            return reorder
    return result
