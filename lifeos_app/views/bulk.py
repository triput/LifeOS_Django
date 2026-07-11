# ==============================================================================
# File: lifeos_app/views/bulk.py
# Description: Bulk Add surface — spreadsheet grid + CSV upload (BL-BULK-001)
# Component: Surfaces / Bulk
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Bulk create UI endpoints for containers and work items."""

from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from lifeos_app.models import DomainCategory, SystemEnums
from lifeos_app.services.bulk_create import (
    BULK_COLUMNS,
    commit_bulk_rows,
    empty_grid_rows,
    parse_delimited_text,
    parse_upload_bytes,
    rows_from_dicts,
    rows_to_grid_dicts,
    template_csv_text,
)


def _page_context(*, grid_rows=None, report=None, notice: str = "") -> dict:
    rows = grid_rows if grid_rows is not None else empty_grid_rows(8)
    return {
        "surface": "bulk",
        "columns": BULK_COLUMNS,
        "columns_json": json.dumps(list(BULK_COLUMNS)),
        "grid_rows": rows,
        "grid_rows_json": json.dumps(rows),
        "report": report,
        "notice": notice,
        "container_types": SystemEnums.ContainerType.choices,
        "item_types": SystemEnums.ItemType.choices,
        "status_choices": SystemEnums.ItemStatus.choices,
        "domains": DomainCategory.objects.filter(is_active=True).order_by("name"),
    }


@login_required
@require_GET
def bulk_view(request):
    """Render Bulk Add spreadsheet + upload surface."""
    return render(request, "surfaces/bulk.html", _page_context())


@login_required
@require_GET
def bulk_template_csv_view(request):
    """Download starter CSV matching the grid schema."""
    response = HttpResponse(template_csv_text(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="lifeos_bulk_template.csv"'
    return response


def _parse_request_rows(request) -> tuple[list, str]:
    """Extract BulkRow list from JSON body, form paste, or uploaded file."""
    notice = ""
    upload = request.FILES.get("file")
    if upload:
        rows = parse_upload_bytes(upload.read(), filename=upload.name)
        notice = f"Loaded {len(rows)} row(s) from {upload.name}."
        return rows, notice

    paste = (request.POST.get("paste_text") or "").strip()
    if paste:
        rows = parse_delimited_text(paste)
        notice = f"Parsed {len(rows)} row(s) from paste."
        return rows, notice

    raw_json = request.POST.get("rows_json") or ""
    if not raw_json and request.content_type and "application/json" in request.content_type:
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
        raw_json = json.dumps(body.get("rows", []))
        all_flag = bool(body.get("all_or_nothing"))
        request._bulk_all_or_nothing = all_flag  # type: ignore[attr-defined]

    if raw_json:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid rows JSON: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("rows_json must be a list of objects.")
        return rows_from_dicts(data), notice

    raise ValueError("Provide grid rows, pasted text, or a CSV file.")


@login_required
@require_http_methods(["POST"])
def bulk_preview_view(request):
    """Parse upload/paste into the editable grid (no DB writes)."""
    try:
        rows, notice = _parse_request_rows(request)
    except ValueError as exc:
        return render(
            request,
            "surfaces/bulk.html",
            _page_context(notice=str(exc)),
            status=400,
        )
    grid = rows_to_grid_dicts(rows) or empty_grid_rows(4)
    # Pad a few blank rows for continued editing.
    while len(grid) < 4:
        grid.extend(empty_grid_rows(1))
    return render(
        request,
        "surfaces/bulk.html",
        _page_context(grid_rows=grid, notice=notice or f"Preview {len(rows)} row(s)."),
    )


@login_required
@require_POST
def bulk_commit_view(request):
    """Commit grid/CSV rows; return report fragment or full page."""
    all_or_nothing = request.POST.get("all_or_nothing") in ("1", "true", "on")
    try:
        rows, notice = _parse_request_rows(request)
        if hasattr(request, "_bulk_all_or_nothing"):
            all_or_nothing = bool(request._bulk_all_or_nothing)
    except ValueError as exc:
        if request.htmx:
            return HttpResponseBadRequest(str(exc))
        return render(
            request,
            "surfaces/bulk.html",
            _page_context(notice=str(exc)),
            status=400,
        )

    try:
        report = commit_bulk_rows(rows, all_or_nothing=all_or_nothing)
    except ValueError as exc:
        if request.headers.get("Accept") == "application/json":
            return JsonResponse({"ok": False, "message": str(exc)}, status=400)
        return render(
            request,
            "surfaces/bulk.html",
            _page_context(
                grid_rows=rows_to_grid_dicts(rows),
                notice=str(exc),
            ),
            status=400,
        )

    summary = (
        f"Created {report.created_containers} container(s), "
        f"{report.created_items} item(s)"
        f"{f'; {report.failed} failed' if report.failed else ''}."
    )
    if notice:
        summary = f"{notice} {summary}"

    context = _page_context(
        grid_rows=empty_grid_rows(8) if report.created_containers + report.created_items else rows_to_grid_dicts(rows),
        report=report,
        notice=summary,
    )

    if request.htmx:
        return render(request, "partials/bulk_report.html", context)
    return render(request, "surfaces/bulk.html", context)
