# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/views.py
# Description: Views implementing auth, focus engine controls, and context HUD logic
# Component: Core / Views
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-07-01
# ==============================================================================
"""View controllers for the LifeOS application.

Contains dashboard views, HUD calculations, focus engine endpoints,
scoped workspace handlers, and authentication routes.
"""

import os
import json
from django.utils import timezone
from django.db import models
from django.db.models import Count, Sum, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.core import serializers

from ..models import WorkspaceContainer, ExecutionItem, AppSettings, DomainCategory, Certification, RecurringConfig, GoogleCalendar, NotionIntegration, parse_duration_to_seconds, format_seconds_to_duration, Tag, CalendarIntegration
from ..telemetry import OpenMeteoAdapter, NoaaKpAdapter


@login_required
def kanban_status_view(request):
    """Render Kanban board grouped by Status."""
    items = ExecutionItem.objects.filter(is_archived=False, is_deleted=False).select_related('domain').prefetch_related('tags').order_by('order', '-created_at')
    
    grouped_items = {s[0]: [] for s in ExecutionItem.STATUS_CHOICES}
    for item in items:
        if item.status in grouped_items:
            grouped_items[item.status].append(item)
            
    context = {
        'grouped_items': grouped_items,
        'status_choices': [s[0] for s in ExecutionItem.STATUS_CHOICES]
    }
    return render(request, 'kanban_status.html', context)

@login_required
def kanban_priority_view(request):
    """Render Kanban board grouped by Priority."""
    items = ExecutionItem.objects.filter(is_archived=False, is_deleted=False).select_related('domain').prefetch_related('tags').order_by('order', '-created_at')
    
    grouped_items = {p[0]: [] for p in ExecutionItem.PRIORITY_CHOICES}
    for item in items:
        if item.priority in grouped_items:
            grouped_items[item.priority].append(item)
            
    context = {
        'grouped_items': grouped_items,
        'priority_choices': [p[0] for p in ExecutionItem.PRIORITY_CHOICES]
    }
    return render(request, 'kanban_priority.html', context)

@login_required
@require_POST
def kanban_move_view(request):
    """
    HTMX endpoint to handle drag-and-drop sortable items.
    Accepts: item_id, column, item_ids[] for ordering.
    """
    item_id = request.POST.get('item_id')
    new_column = request.POST.get('column')
    item_ids_in_order = request.POST.getlist('item_ids')
    grouping = request.POST.get('grouping', 'status') # 'status' or 'priority'
    
    if item_id and new_column:
        item = get_object_or_404(ExecutionItem, id=item_id)
        if grouping == 'status':
            item.status = new_column
        elif grouping == 'priority':
            item.priority = new_column
        item.save()
        
    if item_ids_in_order:
        # Update order of all items in the column
        for idx, i_id in enumerate(item_ids_in_order):
            ExecutionItem.objects.filter(id=i_id).update(order=idx)
            
    return HttpResponse(status=200)

@login_required
def roadmap_view(request):
    """
    Timeline view showing items with due dates in chronological order.
    """
    items = ExecutionItem.objects.filter(
        is_archived=False, 
        is_deleted=False, 
        due_date__isnull=False
    ).select_related('domain').order_by('due_date')
    
    context = {
        'roadmap_items': items,
    }
    return render(request, 'roadmap.html', context)

@login_required
def agenda_view(request):
    """
    Printable daily agenda view based on scheduled allocations.
    """
    from django.utils import timezone
    from datetime import timedelta
    from ..models import ScheduledTaskAllocation
    
    today = timezone.now().date()
    today_start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    today_end = today_start + timedelta(days=1)
    
    allocations = ScheduledTaskAllocation.objects.filter(
        start_time__gte=today_start, 
        start_time__lt=today_end
    ).select_related('execution_item__domain').order_by('start_time')
    
    context = {
        'allocations': allocations,
        'today': today
    }
    return render(request, 'agenda.html', context)

