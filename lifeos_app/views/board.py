# ==============================================================================
# File: lifeos_app/views/board.py
# Description: Boards surface — status Kanban + stack-rank (P4-SURF-BOARD)
# Component: Surfaces / Board
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Kanban and priority stack-rank canvases."""

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from lifeos_app.services.board import BoardFacets, build_board_page, move_item_status, reorder_items


@login_required
def board_view(request):
    """Render Boards surface (status Kanban or stack-rank mode)."""
    from lifeos_app.services.saved_views import views_bar_context

    facets = BoardFacets.from_request(request)
    ctx = build_board_page(facets)
    ctx.update(views_bar_context(surface="board", facets=facets))
    return render(request, "surfaces/board.html", ctx)


@login_required
@require_POST
def board_move_view(request):
    """Move a card to a status column and persist column order."""
    try:
        item_id = int(request.POST.get("item_id", "0"))
    except ValueError:
        return JsonResponse({"ok": False, "message": "Invalid item."}, status=400)
    new_status = (request.POST.get("status") or "").strip()
    raw_order = request.POST.getlist("ordered_ids") or request.POST.getlist("ordered_ids[]")
    if not raw_order:
        # JSON body fallback
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            item_id = int(payload.get("item_id") or item_id)
            new_status = (payload.get("status") or new_status).strip()
            raw_order = payload.get("ordered_ids") or []
        except (json.JSONDecodeError, TypeError, ValueError):
            raw_order = []
    result = move_item_status(item_id, new_status, ordered_ids=[int(x) for x in raw_order if str(x).isdigit() or isinstance(x, int)])
    status = 200 if result.ok else 422
    return JsonResponse({"ok": result.ok, "message": result.message, "status": result.value}, status=status)


@login_required
@require_POST
def board_reorder_view(request):
    """Persist stack_rank from drag order (stack mode or within-column)."""
    raw_order = request.POST.getlist("ordered_ids") or request.POST.getlist("ordered_ids[]")
    if not raw_order:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            raw_order = payload.get("ordered_ids") or []
        except (json.JSONDecodeError, TypeError, ValueError):
            raw_order = []
    ids = []
    for x in raw_order:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    result = reorder_items(ids)
    status = 200 if result.ok else 422
    return JsonResponse({"ok": result.ok, "message": result.message}, status=status)
