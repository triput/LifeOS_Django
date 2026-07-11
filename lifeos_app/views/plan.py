# ==============================================================================
# File: lifeos_app/views/plan.py
# Description: Planner surface and P3 time endpoints
# Component: Surfaces / Plan
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Planner / Agenda — allocations, calendar overlay, schedule & today actions."""

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_POST

from lifeos_app.services.plan import planner_context
from lifeos_app.services.scheduler import run_scheduler
from lifeos_app.services.today import clear_today, plan_today
from lifeos_app.views.htmx import set_cockpit_refresh, set_hx_trigger


@login_required
def plan_view(request):
    """Day timeline planner with #today sidebar."""
    day_str = request.GET.get("day")
    day = None
    if day_str:
        try:
            day = datetime.strptime(day_str, "%Y-%m-%d").date()
        except ValueError:
            day = None
    ctx = planner_context(day, request=request)
    if request.GET.get("calendar_connected") == "1":
        ctx["calendar_message"] = "Google Calendar connected. Click Sync now to pull events."
        ctx["calendar_ok"] = True
    elif request.GET.get("calendar_error") == "oauth_not_configured":
        ctx["calendar_message"] = ctx.get("oauth_setup_message", "Google OAuth is not configured.")
        ctx["calendar_ok"] = False
    elif request.GET.get("calendar_error") == "oauth_invalid":
        detail = request.GET.get("calendar_error_detail", "")
        ctx["calendar_message"] = detail or ctx.get("oauth_setup_message", "Invalid OAuth client configuration.")
        ctx["calendar_ok"] = False
    elif request.GET.get("calendar_error") == "oauth_exchange":
        detail = request.GET.get("calendar_error_detail", "")
        ctx["calendar_message"] = f"Google authorization failed: {detail}"
        ctx["calendar_ok"] = False
    return render(request, "surfaces/plan.html", ctx)


@login_required
@require_POST
def schedule_run_view(request):
    """Run deterministic scheduler; refresh planner fragment."""
    result = run_scheduler()
    ctx = planner_context()
    ctx["schedule_message"] = result.message
    ctx["schedule_ok"] = result.ok
    response = render(request, "partials/plan_timeline.html", ctx)
    if result.ok:
        set_hx_trigger(response, "plan-reload")
    return response


@login_required
@require_POST
def today_plan_view(request):
    """Multi-home items onto #today (optional item_ids CSV)."""
    raw_ids = request.POST.get("item_ids", "")
    item_ids = [int(x) for x in raw_ids.split(",") if x.strip().isdigit()] or None
    query = request.POST.get("query", "")
    result = plan_today(item_ids=item_ids, query=query)
    ctx = planner_context()
    ctx["today_message"] = result.message
    response = render(request, "partials/plan_today_panel.html", ctx)
    set_cockpit_refresh(response)
    return response


@login_required
@require_POST
def today_clear_view(request):
    """Remove non-primary #today links."""
    result = clear_today()
    ctx = planner_context()
    ctx["today_message"] = result.message
    response = render(request, "partials/plan_today_panel.html", ctx)
    set_cockpit_refresh(response)
    return response
