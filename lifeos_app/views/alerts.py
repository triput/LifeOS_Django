# ==============================================================================
# File: lifeos_app/views/alerts.py
# Description: Alerts glyph and sheet (ENG-NOTIFY in-app)
# Component: Surfaces / Alerts
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Ambient alerts — pending reminders, snooze, ack."""

import json

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from lifeos_app.models import ReminderDispatch, SystemEnums
from lifeos_app.services.notify import pending_alert_count


@login_required
def alerts_glyph_view(request):
    """HTMX fragment for header alert count."""
    return render(request, "partials/alerts_glyph.html", {"alert_count": pending_alert_count()})


@login_required
def alerts_sheet_view(request):
    """Progressive triage overlay content."""
    now = timezone.now()
    reminders = (
        ReminderDispatch.objects.filter(
            status__in=[
                SystemEnums.ReminderDispatchStatus.PENDING,
                SystemEnums.ReminderDispatchStatus.FAILED,
            ]
        )
        .select_related("execution_item")
        .order_by("fire_at")[:50]
    )
    return render(request, "partials/alerts_sheet.html", {"reminders": reminders, "now": now})


@login_required
@require_POST
def alerts_snooze_view(request, dispatch_id: int):
    """Snooze a reminder by 30 minutes."""
    dispatch = get_object_or_404(ReminderDispatch, pk=dispatch_id)
    dispatch.status = SystemEnums.ReminderDispatchStatus.SNOOZED
    dispatch.snooze_until = timezone.now() + timedelta(minutes=30)
    dispatch.save(update_fields=["status", "snooze_until", "updated_at"])
    return alerts_sheet_view(request)


@login_required
@require_POST
def alerts_ack_view(request, dispatch_id: int):
    """Acknowledge / dismiss a reminder."""
    dispatch = get_object_or_404(ReminderDispatch, pk=dispatch_id)
    dispatch.status = SystemEnums.ReminderDispatchStatus.SENT
    dispatch.sent_at = timezone.now()
    dispatch.save(update_fields=["status", "sent_at", "updated_at"])
    response = alerts_sheet_view(request)
    response["HX-Trigger"] = "alerts-refresh"
    return response
