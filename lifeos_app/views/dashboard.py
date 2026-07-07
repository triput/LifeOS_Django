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
def dashboard_view(request):
    """
    Renders the consolidated workspace dashboard and the Unified Domain Context HUD.
    """
    settings = AppSettings.get_solo()
    card_names = settings.dashboard_card_names or {}
    hud_env_name = card_names.get('hud_env', 'ENVIRONMENTAL HUD')
    hud_domain_name = card_names.get('hud_domain', 'DOMAIN VELOCITY')
    hud_para_name = card_names.get('hud_para', 'PARA ALLOCATION')

    # 1. Active (incomplete, non-deleted, non-archived) actionable ExecutionItems (excluding Inbox ideas)
    active_items = ExecutionItem.objects.filter(
        is_completed=False,
        is_deleted=False,
        is_archived=False
    ).exclude(status__in=['Inbox', 'Backlog']).order_by('created_at').select_related('domain').prefetch_related('tags')

    # Filter scheduled/upcoming items
    upcoming_items = ExecutionItem.objects.filter(
        is_completed=False,
        is_deleted=False,
        is_archived=False
    ).exclude(status__in=['Inbox', 'Backlog']).filter(
        models.Q(start_date__isnull=False) | 
        models.Q(due_date__isnull=False) | 
        models.Q(fuzzy_timeframe__isnull=False)
    ).order_by('due_date', 'start_date').select_related('domain').prefetch_related('tags')

    pinned_items = active_items.filter(is_pinned=True)
    
    # Exclude pinned and upcoming items from the generic backlog list to avoid duplicates
    unpinned_items = active_items.filter(is_pinned=False).exclude(
        id__in=upcoming_items.values_list('id', flat=True)
    )

    # 2. Dynamic progress vectors by Domain Category (FR-HUD-001)
    domain_stats = ExecutionItem.objects.filter(
        is_deleted=False,
        is_archived=False
    ).values('domain__name', 'domain__color', 'domain__icon').annotate(
        total_tasks=Count('id'),
        completed_tasks=Count('id', filter=models.Q(is_completed=True)),
        total_time_spent=Sum('time_spent_seconds'),
    )

    # 3. Dynamic progress vectors by PARA Category (FR-HUD-001)
    para_stats = ExecutionItem.objects.filter(
        is_deleted=False,
        is_archived=False
    ).values('para_category').annotate(
        total_tasks=Count('id'),
        completed_tasks=Count('id', filter=models.Q(is_completed=True)),
        total_time_spent=Sum('time_spent_seconds'),
    )

    # Process stats to ensure clean list output with percentages
    processed_domains = []
    for stat in domain_stats:
        cat = stat['domain__name'] or 'Uncategorized'
        color = stat['domain__color'] or '#9CA3AF'
        icon = stat['domain__icon'] or 'folder'
        total = stat['total_tasks']
        completed = stat['completed_tasks']
        time_spent = stat['total_time_spent'] or 0
        rate = int((completed / total) * 100) if total > 0 else 0
        processed_domains.append({
            'category': cat,
            'color': color,
            'icon': icon,
            'total': total,
            'completed': completed,
            'rate': rate,
            'time_spent': time_spent
        })

    processed_para = []
    for stat in para_stats:
        cat = stat['para_category'] or 'Uncategorized'
        total = stat['total_tasks']
        completed = stat['completed_tasks']
        time_spent = stat['total_time_spent'] or 0
        rate = int((completed / total) * 100) if total > 0 else 0
        processed_para.append({
            'category': cat,
            'total': total,
            'completed': completed,
            'rate': rate,
            'time_spent': time_spent
        })

    # 4. Environment Telemetry from Open-Meteo & NOAA SWPC (FR-HUD-004)
    weather_adapter = OpenMeteoAdapter()
    weather_data = weather_adapter.get_telemetry()
    
    kp_adapter = NoaaKpAdapter()
    kp_data = kp_adapter.get_kp_index()

    context = {
        'pinned_tasks': pinned_items,
        'unpinned_tasks': unpinned_items,
        'upcoming_tasks': upcoming_items,
        'domain_stats': processed_domains,
        'para_stats': processed_para,
        'weather': weather_data,
        'kp': kp_data,
        'hud_names': {
            'hud_env': hud_env_name,
            'hud_domain': hud_domain_name,
            'hud_para': hud_para_name,
        }
    }
    return render(request, 'dashboard.html', context)

@login_required
def quick_entry_view(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        dump_type = request.POST.get('dump_type', 'Task')
        
        if title:
            if dump_type == 'Task':
                # Create unassigned item in Inbox
                ExecutionItem.objects.create(
                    title=title,
                    item_type='Task',
                    status='Inbox',
                    is_completed=False
                )
                msg = f"Task '{title}' dumped to Inbox!"
            else:
                # Create WorkspaceContainer
                WorkspaceContainer.objects.create(
                    title=title,
                    container_type=dump_type
                )
                msg = f"{dump_type} '{title}' created successfully!"
                
            # If HTMX request, return a partial swapping the form and showing toast
            if request.headers.get('HX-Request'):
                return render(request, 'partials/quick_entry_success.html', {'title': title, 'msg': msg})
            
            messages.success(request, msg)
        
        next_url = request.META.get('HTTP_REFERER', 'dashboard')
        return redirect(next_url)
    return redirect('dashboard')

@login_required
def clear_toast_view(request):
    return render(request, 'partials/clear_toast.html')

@login_required
def triage_view(request):
    from django.db.models import Q
    inbox_items = ExecutionItem.objects.filter(
        status='Inbox',
        is_deleted=False,
        is_archived=False
    ).order_by('-created_at')
    
    orphan_containers = WorkspaceContainer.objects.filter(
        parent=None,
        is_archived=False
    ).filter(
        domain__isnull=True
    ).filter(
        Q(para_category__isnull=True) | Q(para_category='')
    ).order_by('-created_at')
    
    containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('container_type', 'title')
    parent_tasks = ExecutionItem.objects.filter(
        is_deleted=False, 
        is_archived=False, 
        item_type__in=['Task', 'LearningTask']
    ).exclude(status='Inbox').order_by('item_type', 'title')
    
    domains = DomainCategory.objects.all().order_by('name')
    paras = [choice[0] for choice in ExecutionItem.PARA_CATEGORIES]
    types = [choice[0] for choice in ExecutionItem.ITEM_TYPES]
    statuses = [choice[0] for choice in ExecutionItem.STATUS_CHOICES if choice[0] != 'Inbox']
    priorities = [choice[0] for choice in ExecutionItem.PRIORITY_CHOICES]
    
    context = {
        'inbox_items': inbox_items,
        'orphan_containers': orphan_containers,
        'containers': containers,
        'parent_tasks': parent_tasks,
        'domains': domains,
        'paras': paras,
        'types': types,
        'statuses': statuses,
        'priorities': priorities,
    }
    return render(request, 'triage.html', context)

@login_required
def process_triage_view(request, item_id):
    if request.method == 'POST':
        item = get_object_or_404(ExecutionItem, id=item_id)
        parent_raw = request.POST.get('container')
        domain = request.POST.get('domain')
        para = request.POST.get('para')
        item_type = request.POST.get('item_type', 'Task')
        duration = request.POST.get('duration_estimate')
        priority = request.POST.get('priority', 'Medium')
        
        status = request.POST.get('status')
        if not status:
            if item.start_date or item.due_date:
                status = 'Planned'
            else:
                status = 'Backlog'
        
        if parent_raw:
            parent_raw = str(parent_raw).strip()
            if parent_raw.startswith('container_'):
                pid = parent_raw.split('_')[1]
                container = get_object_or_404(WorkspaceContainer, id=pid)
                item.content_type = ContentType.objects.get_for_model(WorkspaceContainer)
                item.object_id = container.id
            elif parent_raw.startswith('task_'):
                pid = parent_raw.split('_')[1]
                parent_task = get_object_or_404(ExecutionItem, id=pid)
                item.content_type = ContentType.objects.get_for_model(ExecutionItem)
                item.object_id = parent_task.id
            elif parent_raw.isdigit():
                # Legacy V2 tests fallback (pure container integer ID)
                container = get_object_or_404(WorkspaceContainer, id=parent_raw)
                item.content_type = ContentType.objects.get_for_model(WorkspaceContainer)
                item.object_id = container.id
        else:
            item.content_type = None
            item.object_id = None
            
        if domain:
            try:
                dom_cat = DomainCategory.objects.get(name=domain)
                item.domain = dom_cat
            except DomainCategory.DoesNotExist:
                dom_cat = DomainCategory.objects.filter(name=domain).first()
                if dom_cat:
                    item.domain = dom_cat
        if para:
            item.para_category = para
            
        item.item_type = item_type
        item.priority = priority
        item.status = status
        
        if duration:
            # Parse human string (e.g. "1h 30m" -> 90 minutes)
            secs = parse_duration_to_seconds(duration)
            item.duration_estimate = max(1, secs // 60)
                
        item.save()
        
        if request.headers.get('HX-Request'):
            return HttpResponse("") # HTMX empty response removes element
            
        return redirect('triage')
    return redirect('triage')

@login_required
def process_container_triage_view(request, container_id):
    if request.method == 'POST':
        container = get_object_or_404(WorkspaceContainer, id=container_id)
        parent_raw = request.POST.get('container')
        domain = request.POST.get('domain')
        para = request.POST.get('para')
        
        if parent_raw:
            parent_raw = str(parent_raw).strip()
            if parent_raw.startswith('container_'):
                pid = parent_raw.split('_')[1]
                parent_container = get_object_or_404(WorkspaceContainer, id=pid)
                if parent_container.id != container.id:
                    container.parent = parent_container
            elif parent_raw.isdigit():
                parent_container = get_object_or_404(WorkspaceContainer, id=parent_raw)
                if parent_container.id != container.id:
                    container.parent = parent_container
        
        if domain:
            try:
                dom_cat = DomainCategory.objects.get(name=domain)
                container.domain = dom_cat
            except DomainCategory.DoesNotExist:
                dom_cat = DomainCategory.objects.filter(name=domain).first()
                if dom_cat:
                    container.domain = dom_cat
                    
        if para:
            container.para_category = para
            
        container.priority = request.POST.get('priority', 'Medium')
        container.urgency = request.POST.get('urgency', 'Normal')
        
        try:
            container.save()
        except ValidationError as e:
            messages.error(request, f"Error: {e.messages[0]}")
            if request.headers.get('HX-Request'):
                from django.urls import reverse
                response = HttpResponse(status=200)
                response['HX-Redirect'] = reverse('triage')
                return response
            return redirect('triage')
        
        if request.headers.get('HX-Request'):
            return HttpResponse("")
        return redirect('triage')
    return redirect('triage')

@login_required
def container_detail_view(request, container_id):
    """
    Renders workspace view scoped to a selected WorkspaceContainer.
    Excludes completed, archived, and soft-deleted items by default.
    """
    container = get_object_or_404(WorkspaceContainer, id=container_id, is_archived=False)
    
    # Get immediate child containers
    child_containers = WorkspaceContainer.objects.filter(
        parent=container,
        is_archived=False
    ).order_by('order', 'title')

    # Fetch ExecutionItems linked to this WorkspaceContainer (generic relation)
    container_type = ContentType.objects.get_for_model(WorkspaceContainer)
    container_items = ExecutionItem.objects.filter(
        content_type=container_type,
        object_id=container.id,
        is_completed=False,
        is_deleted=False,
        is_archived=False
    ).order_by('created_at')

    context = {
        'container': container,
        'child_containers': child_containers,
        'tasks': container_items,
    }
    return render(request, 'container_detail.html', context)

@login_required
@require_POST
def toggle_task(request, task_id):
    """
    Toggles completion state on an ExecutionItem.
    """
    task = get_object_or_404(ExecutionItem, id=task_id, is_deleted=False)
    task.is_completed = not task.is_completed
    
    # If completed, stop any running timers
    if task.is_completed and task.is_active:
        if task.started_at:
            delta = timezone.now() - task.started_at
            task.time_spent_seconds += int(delta.total_seconds())
        task.is_active = False
        task.started_at = None
        
    task.save()
    
    # Try to redirect to referrer, fallback to dashboard
    next_url = request.META.get('HTTP_REFERER', 'dashboard')
    if 'container/' in next_url:
        return redirect(next_url)
    return redirect('dashboard')

@login_required
def task_action_view(request):
    """
    Consolidated focus engine endpoint for ExecutionItem focus actions.
    Supports start, pause, resume, and stop actions.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON format'}, status=400)

    task_id = data.get('task_id')
    action = data.get('action') # 'start', 'stop', 'pause', 'resume'
    
    if not task_id or not action:
        return JsonResponse({'error': 'Missing parameters'}, status=400)

    task = get_object_or_404(ExecutionItem, id=task_id, is_deleted=False)

    if action in ['start', 'resume']:
        # Ensure only one task can be active at a time to prevent leakage
        active_timers = ExecutionItem.objects.filter(is_active=True).exclude(id=task.id)
        for active_task in active_timers:
            if active_task.started_at:
                delta = timezone.now() - active_task.started_at
                active_task.time_spent_seconds += int(delta.total_seconds())
            active_task.is_active = False
            active_task.started_at = None
            active_task.save()

        task.is_active = True
        task.started_at = timezone.now()
        task.save()
        return JsonResponse({
            'status': 'started', 
            'started_at': task.started_at.isoformat(),
            'time_spent_seconds': task.time_spent_seconds
        })

    elif action in ['stop', 'pause']:
        if task.is_active and task.started_at:
            delta = timezone.now() - task.started_at
            task.time_spent_seconds += int(delta.total_seconds())
        
        task.is_active = False
        task.started_at = None
        task.save()
        return JsonResponse({
            'status': 'stopped', 
            'total_seconds': task.time_spent_seconds
        })
            
    return JsonResponse({'error': 'Invalid action'}, status=400)

@login_required
@require_POST
def toggle_pin_view(request, item_id):
    item = get_object_or_404(ExecutionItem, id=item_id, is_deleted=False)
    item.is_pinned = not item.is_pinned
    item.save()
    
    next_url = request.META.get('HTTP_REFERER', 'dashboard')
    return redirect(next_url)

