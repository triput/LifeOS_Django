# ==============================================================================
# File: lifeos_app/services/bulk_create.py
# Description: Bulk create containers + items from grid/CSV (BL-BULK-001)
# Component: Services / Bulk authoring
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Spreadsheet / CSV bulk create for WorkspaceContainer and ExecutionItem.

Track A (grid) and Track B (CSV upload) share one column schema. Soft-fail is
the default: each row uses a savepoint so one bad row does not roll back the
batch. Parent may be an existing ``#slug`` or a within-batch ``row_id``.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from django.db import transaction
from django.utils.text import slugify

from lifeos_app.models import (
    DomainCategory,
    ExecutionItem,
    ItemContainerLink,
    SystemEnums,
    WorkspaceContainer,
)
from lifeos_app.services.tags import resolve_tag
from lifeos_app.services.time_format import parse_duration_minutes

# Canonical header order for template CSV + grid columns.
BULK_COLUMNS: tuple[str, ...] = (
    "row_id",
    "kind",
    "title",
    "type",
    "parent",
    "slug",
    "domain",
    "status",
    "priority",
    "estimate",
    "tags",
    "para",
)

_HEADER_ALIASES = {
    "row": "row_id",
    "id": "row_id",
    "temp_id": "row_id",
    "kind": "kind",
    "entity": "kind",
    "title": "title",
    "name": "title",
    "type": "type",
    "container_type": "type",
    "item_type": "type",
    "parent": "parent",
    "parent_slug": "parent",
    "home": "parent",
    "slug": "slug",
    "domain": "domain",
    "status": "status",
    "priority": "priority",
    "pri": "priority",
    "estimate": "estimate",
    "est": "estimate",
    "estimated_minutes": "estimate",
    "tags": "tags",
    "tag": "tags",
    "para": "para",
    "para_state": "para",
}

_KIND_ALIASES = {
    "container": "container",
    "node": "container",
    "c": "container",
    "item": "item",
    "leaf": "item",
    "task": "item",
    "i": "item",
}

_PRIORITY_ALIASES = {
    "1": 1,
    "p1": 1,
    "critical": 1,
    "2": 2,
    "p2": 2,
    "high": 2,
    "3": 3,
    "p3": 3,
    "normal": 3,
    "4": 4,
    "p4": 4,
    "low": 4,
}


@dataclass
class BulkRow:
    """One normalized bulk-create row (grid or CSV)."""

    line_no: int
    row_id: str = ""
    kind: str = ""
    title: str = ""
    type: str = ""
    parent: str = ""
    slug: str = ""
    domain: str = ""
    status: str = ""
    priority: str = ""
    estimate: str = ""
    tags: str = ""
    para: str = ""

    def is_blank(self) -> bool:
        return not (self.title or "").strip() and not (self.kind or "").strip()


@dataclass
class BulkRowResult:
    """Per-row outcome after commit."""

    line_no: int
    ok: bool
    message: str
    title: str = ""
    kind: str = ""
    created_id: int | None = None


@dataclass
class BulkCommitResult:
    """Batch summary for UI report."""

    created_containers: int = 0
    created_items: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[BulkRowResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and (self.created_containers + self.created_items) > 0


def template_csv_text() -> str:
    """Downloadable starter CSV with header + two example rows."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(BULK_COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerow(
        {
            "row_id": "r1",
            "kind": "container",
            "title": "Example Epic",
            "type": "EPIC",
            "parent": "",
            "slug": "example-epic",
            "domain": "tech",
            "status": "",
            "priority": "2",
            "estimate": "",
            "tags": "",
            "para": "PROJECT",
        }
    )
    writer.writerow(
        {
            "row_id": "r2",
            "kind": "item",
            "title": "First task under example epic",
            "type": "TASK",
            "parent": "r1",
            "slug": "",
            "domain": "",
            "status": "BACKLOG",
            "priority": "3",
            "estimate": "1h",
            "tags": "deep-work",
            "para": "",
        }
    )
    return buf.getvalue()


def empty_grid_rows(count: int = 8) -> list[dict[str, str]]:
    """Blank dict rows for the spreadsheet UI."""
    return [{col: "" for col in BULK_COLUMNS} for _ in range(max(1, count))]


def normalize_header(name: str) -> str | None:
    """Map a CSV header cell to a canonical column name."""
    key = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return _HEADER_ALIASES.get(key)


def rows_from_dicts(raw_rows: Iterable[dict[str, Any]], *, start_line: int = 1) -> list[BulkRow]:
    """Build BulkRow list from dicts (grid JSON or mapped CSV)."""
    out: list[BulkRow] = []
    for offset, raw in enumerate(raw_rows):
        mapped: dict[str, str] = {}
        for key, value in (raw or {}).items():
            canon = normalize_header(str(key)) if key not in BULK_COLUMNS else key
            if canon is None and str(key) in BULK_COLUMNS:
                canon = str(key)
            if canon is None:
                continue
            mapped[canon] = "" if value is None else str(value).strip()
        row = BulkRow(
            line_no=start_line + offset,
            row_id=mapped.get("row_id", ""),
            kind=mapped.get("kind", ""),
            title=mapped.get("title", ""),
            type=mapped.get("type", ""),
            parent=mapped.get("parent", ""),
            slug=mapped.get("slug", ""),
            domain=mapped.get("domain", ""),
            status=mapped.get("status", ""),
            priority=mapped.get("priority", ""),
            estimate=mapped.get("estimate", ""),
            tags=mapped.get("tags", ""),
            para=mapped.get("para", ""),
        )
        if not row.is_blank():
            out.append(row)
    return out


def parse_delimited_text(text: str) -> list[BulkRow]:
    """Parse CSV or TSV text (with or without header) into BulkRow list."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []

    sample = raw[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
        if "\t" in sample and sample.count("\t") >= sample.count(","):
            dialect = csv.excel_tab

    reader = csv.reader(io.StringIO(raw), dialect)
    rows_list = list(reader)
    if not rows_list:
        return []

    first = [c.strip() for c in rows_list[0]]
    mapped_headers = [normalize_header(h) for h in first]
    has_header = any(h is not None for h in mapped_headers)

    if has_header:
        headers = [h or f"col{i}" for i, h in enumerate(mapped_headers)]
        dicts = []
        for cells in rows_list[1:]:
            d = {}
            for i, header in enumerate(headers):
                if header.startswith("col") and normalize_header(header) is None:
                    continue
                canon = header if header in BULK_COLUMNS else normalize_header(header)
                if canon:
                    d[canon] = cells[i].strip() if i < len(cells) else ""
            dicts.append(d)
        return rows_from_dicts(dicts, start_line=2)

    # No header — assume canonical column order (kind, title, …) starting at kind.
    # Allow short rows: kind, title, type, parent
    dicts = []
    for cells in rows_list:
        padded = list(cells) + [""] * len(BULK_COLUMNS)
        # If first cell looks like a kind, start at kind (skip row_id).
        first_cell = (cells[0] if cells else "").strip().lower()
        if first_cell in _KIND_ALIASES:
            values = [""] + padded[: len(BULK_COLUMNS) - 1]
        else:
            values = padded[: len(BULK_COLUMNS)]
        dicts.append({col: values[i].strip() for i, col in enumerate(BULK_COLUMNS)})
    return rows_from_dicts(dicts, start_line=1)


def parse_upload_bytes(data: bytes, filename: str = "") -> list[BulkRow]:
    """Decode uploaded file bytes as CSV/TSV (xlsx not supported in MVP)."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        raise ValueError("Excel (.xlsx) upload is not enabled yet — export CSV and retry.")
    text = data.decode("utf-8-sig")
    return parse_delimited_text(text)


def _normalize_kind(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _KIND_ALIASES.get(key, "")


def _normalize_parent_token(raw: str) -> str:
    token = (raw or "").strip()
    if token.startswith("#"):
        token = token[1:].strip()
    return token


def _resolve_domain(raw: str) -> DomainCategory | None:
    token = (raw or "").strip()
    if not token:
        return None
    domain = DomainCategory.objects.filter(slug__iexact=token).first()
    if domain:
        return domain
    return DomainCategory.objects.filter(name__iexact=token).first()


def _resolve_priority(raw: str) -> int:
    key = (raw or "").strip().lower()
    if not key:
        return SystemEnums.PriorityLevel.NORMAL
    if key in _PRIORITY_ALIASES:
        return _PRIORITY_ALIASES[key]
    raise ValueError(f"Unknown priority: {raw!r}")


def _resolve_status(raw: str) -> str:
    token = (raw or "").strip().upper().replace(" ", "_")
    if not token:
        return SystemEnums.ItemStatus.BACKLOG
    valid = {c.value for c in SystemEnums.ItemStatus}
    if token not in valid:
        raise ValueError(f"Unknown status: {raw!r}")
    return token


def _resolve_container_type(raw: str) -> str:
    token = (raw or "").strip().upper().replace(" ", "_")
    if not token:
        return SystemEnums.ContainerType.PROJECT
    valid = {c.value for c in SystemEnums.ContainerType}
    if token not in valid:
        raise ValueError(f"Unknown container type: {raw!r}")
    return token


def _resolve_item_type(raw: str) -> str:
    token = (raw or "").strip().upper().replace(" ", "_")
    if not token:
        return SystemEnums.ItemType.TASK
    valid = {c.value for c in SystemEnums.ItemType}
    if token not in valid:
        raise ValueError(f"Unknown item type: {raw!r}")
    return token


def _resolve_para(raw: str) -> str:
    token = (raw or "").strip().upper().replace(" ", "_")
    if not token:
        return SystemEnums.PARACategory.PROJECT
    valid = {c.value for c in SystemEnums.PARACategory}
    if token not in valid:
        raise ValueError(f"Unknown PARA state: {raw!r}")
    return token


def _parse_tags(raw: str) -> list[str]:
    if not (raw or "").strip():
        return []
    parts = re.split(r"[,;|]", raw)
    return [p.strip().lstrip("@") for p in parts if p.strip()]


def _parse_estimate(raw: str) -> int:
    token = (raw or "").strip()
    if not token:
        return 30
    minutes = parse_duration_minutes(token)
    if minutes is None:
        raise ValueError(f"Unknown estimate: {raw!r}")
    return minutes


def _topo_containers(rows: list[BulkRow]) -> list[BulkRow]:
    """Order container rows so within-batch parents precede children."""
    containers = [r for r in rows if _normalize_kind(r.kind) == "container"]
    by_id = {r.row_id.strip(): r for r in containers if r.row_id.strip()}
    visiting: set[str] = set()
    done: set[str] = set()
    ordered: list[BulkRow] = []

    def visit(row: BulkRow) -> None:
        rid = row.row_id.strip()
        if rid and rid in done:
            return
        if rid and rid in visiting:
            raise ValueError(f"Circular parent refs involving row_id {rid!r}")
        if rid:
            visiting.add(rid)
        parent = _normalize_parent_token(row.parent)
        if parent and parent in by_id:
            visit(by_id[parent])
        ordered.append(row)
        if rid:
            visiting.discard(rid)
            done.add(rid)

    for row in containers:
        visit(row)
    return ordered


def _resolve_container_ref(
    token: str,
    *,
    batch_containers: dict[str, WorkspaceContainer],
) -> WorkspaceContainer | None:
    key = _normalize_parent_token(token)
    if not key:
        return None
    if key in batch_containers:
        return batch_containers[key]
    return WorkspaceContainer.objects.filter(slug__iexact=key).first()


def _create_container_row(
    row: BulkRow,
    *,
    batch_containers: dict[str, WorkspaceContainer],
) -> WorkspaceContainer:
    title = row.title.strip()
    if not title:
        raise ValueError("Title required")
    kind = _normalize_kind(row.kind)
    if kind != "container":
        raise ValueError(f"Expected kind=container, got {row.kind!r}")

    parent = None
    if row.parent.strip():
        parent = _resolve_container_ref(row.parent, batch_containers=batch_containers)
        if parent is None:
            raise ValueError(f"Unknown parent container: {row.parent!r}")

    domain = _resolve_domain(row.domain)
    if row.domain.strip() and domain is None:
        raise ValueError(f"Unknown domain: {row.domain!r}")

    container = WorkspaceContainer(
        title=title,
        container_type=_resolve_container_type(row.type),
        para_state=_resolve_para(row.para),
        domain=domain,
        parent=parent,
        priority=_resolve_priority(row.priority),
    )
    if row.slug.strip():
        container.slug = slugify(row.slug.strip())
    container.save()

    for tag_token in _parse_tags(row.tags):
        container.tags.add(resolve_tag(tag_token))

    if row.row_id.strip():
        batch_containers[row.row_id.strip()] = container
    batch_containers[container.slug] = container
    return container


def _create_item_row(
    row: BulkRow,
    *,
    batch_containers: dict[str, WorkspaceContainer],
) -> ExecutionItem:
    title = row.title.strip()
    if not title:
        raise ValueError("Title required")
    kind = _normalize_kind(row.kind)
    if kind != "item":
        raise ValueError(f"Expected kind=item, got {row.kind!r}")

    item = ExecutionItem.objects.create(
        title=title,
        item_type=_resolve_item_type(row.type),
        status=_resolve_status(row.status),
        priority=_resolve_priority(row.priority),
        estimated_minutes=_parse_estimate(row.estimate),
    )

    home = None
    if row.parent.strip():
        home = _resolve_container_ref(row.parent, batch_containers=batch_containers)
        if home is None:
            raise ValueError(f"Unknown parent/home container: {row.parent!r}")
        ItemContainerLink.objects.create(item=item, container=home, is_primary=True)
    else:
        inbox = WorkspaceContainer.objects.filter(slug="inbox").first()
        if inbox:
            ItemContainerLink.objects.create(item=item, container=inbox, is_primary=False)

    for tag_token in _parse_tags(row.tags):
        item.tags.add(resolve_tag(tag_token))

    return item


@transaction.atomic
def commit_bulk_rows(
    rows: list[BulkRow],
    *,
    all_or_nothing: bool = False,
) -> BulkCommitResult:
    """Create containers then items. Soft-fail per row unless ``all_or_nothing``."""
    result = BulkCommitResult()
    if not rows:
        result.results.append(
            BulkRowResult(line_no=0, ok=False, message="No rows to create.")
        )
        result.failed = 1
        return result

    # Validate kinds early for clearer reports.
    prepared: list[BulkRow] = []
    for row in rows:
        if row.is_blank():
            result.skipped += 1
            continue
        kind = _normalize_kind(row.kind)
        if not kind:
            result.failed += 1
            result.results.append(
                BulkRowResult(
                    line_no=row.line_no,
                    ok=False,
                    title=row.title,
                    message=f"Unknown kind: {row.kind!r} (use container or item)",
                )
            )
            if all_or_nothing:
                raise ValueError(result.results[-1].message)
            continue
        prepared.append(
            BulkRow(
                line_no=row.line_no,
                row_id=row.row_id,
                kind=kind,
                title=row.title,
                type=row.type,
                parent=row.parent,
                slug=row.slug,
                domain=row.domain,
                status=row.status,
                priority=row.priority,
                estimate=row.estimate,
                tags=row.tags,
                para=row.para,
            )
        )

    batch_containers: dict[str, WorkspaceContainer] = {}

    try:
        container_order = _topo_containers(prepared)
    except ValueError as exc:
        result.failed += 1
        result.results.append(BulkRowResult(line_no=0, ok=False, message=str(exc)))
        if all_or_nothing:
            raise
        container_order = [r for r in prepared if r.kind == "container"]

    for row in container_order:
        if all_or_nothing:
            try:
                created = _create_container_row(row, batch_containers=batch_containers)
            except Exception as exc:
                raise ValueError(f"Line {row.line_no}: {exc}") from exc
            result.created_containers += 1
            result.results.append(
                BulkRowResult(
                    line_no=row.line_no,
                    ok=True,
                    title=created.title,
                    kind="container",
                    created_id=created.pk,
                    message=f"Created container #{created.slug}",
                )
            )
            continue

        sid = transaction.savepoint()
        try:
            created = _create_container_row(row, batch_containers=batch_containers)
            transaction.savepoint_commit(sid)
            result.created_containers += 1
            result.results.append(
                BulkRowResult(
                    line_no=row.line_no,
                    ok=True,
                    title=created.title,
                    kind="container",
                    created_id=created.pk,
                    message=f"Created container #{created.slug}",
                )
            )
        except Exception as exc:
            transaction.savepoint_rollback(sid)
            result.failed += 1
            result.results.append(
                BulkRowResult(
                    line_no=row.line_no,
                    ok=False,
                    title=row.title,
                    kind="container",
                    message=str(exc),
                )
            )

    for row in prepared:
        if row.kind != "item":
            continue
        if all_or_nothing:
            try:
                created = _create_item_row(row, batch_containers=batch_containers)
            except Exception as exc:
                raise ValueError(f"Line {row.line_no}: {exc}") from exc
            result.created_items += 1
            result.results.append(
                BulkRowResult(
                    line_no=row.line_no,
                    ok=True,
                    title=created.title,
                    kind="item",
                    created_id=created.pk,
                    message=f"Created item #{created.pk}",
                )
            )
            continue

        sid = transaction.savepoint()
        try:
            created = _create_item_row(row, batch_containers=batch_containers)
            transaction.savepoint_commit(sid)
            result.created_items += 1
            result.results.append(
                BulkRowResult(
                    line_no=row.line_no,
                    ok=True,
                    title=created.title,
                    kind="item",
                    created_id=created.pk,
                    message=f"Created item #{created.pk}",
                )
            )
        except Exception as exc:
            transaction.savepoint_rollback(sid)
            result.failed += 1
            result.results.append(
                BulkRowResult(
                    line_no=row.line_no,
                    ok=False,
                    title=row.title,
                    kind="item",
                    message=str(exc),
                )
            )

    if all_or_nothing and result.failed:
        raise ValueError("Bulk create failed (all-or-nothing).")

    result.results.sort(key=lambda r: r.line_no)
    return result


def rows_to_grid_dicts(rows: list[BulkRow]) -> list[dict[str, str]]:
    """Serialize BulkRow list back into grid-friendly dicts."""
    out = []
    for row in rows:
        out.append(
            {
                "row_id": row.row_id,
                "kind": row.kind,
                "title": row.title,
                "type": row.type,
                "parent": row.parent,
                "slug": row.slug,
                "domain": row.domain,
                "status": row.status,
                "priority": row.priority,
                "estimate": row.estimate,
                "tags": row.tags,
                "para": row.para,
            }
        )
    return out
