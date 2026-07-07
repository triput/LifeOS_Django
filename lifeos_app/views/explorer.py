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
def explorer_view(request):
    root_containers = WorkspaceContainer.objects.filter(
        parent=None,
        is_archived=False
    )
    
    orphan_items = ExecutionItem.objects.filter(
        content_type=None,
        is_deleted=False,
        is_archived=False
    )
    
    tag_ids_param = request.GET.get('tags')
    exclude_tag_ids_param = request.GET.get('exclude_tags')
    untagged_param = request.GET.get('untagged')
    
    if tag_ids_param:
        tag_ids = [int(tid) for tid in tag_ids_param.split(',') if tid.strip().isdigit()]
        for tid in tag_ids:
            root_containers = root_containers.filter(tags__id=tid)
            orphan_items = orphan_items.filter(tags__id=tid)
            
    if exclude_tag_ids_param:
        exclude_tag_ids = [int(tid) for tid in exclude_tag_ids_param.split(',') if tid.strip().isdigit()]
        if exclude_tag_ids:
            root_containers = root_containers.exclude(tags__id__in=exclude_tag_ids)
            orphan_items = orphan_items.exclude(tags__id__in=exclude_tag_ids)
            
    if untagged_param == 'true':
        root_containers = root_containers.filter(tags__isnull=True)
        orphan_items = orphan_items.filter(tags__isnull=True)
        
    root_containers = root_containers.order_by('container_type', 'title').distinct()
    orphan_items = orphan_items.order_by('status', '-created_at').distinct()
    
    all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
    all_tags = Tag.objects.all().order_by('name')
    
    context = {
        'root_containers': root_containers,
        'orphan_items': orphan_items,
        'all_containers': all_containers,
        'all_tags': all_tags,
        'current_tags': tag_ids_param,
        'current_exclude': exclude_tag_ids_param,
        'current_untagged': untagged_param,
    }
    return render(request, 'explorer.html', context)

@login_required
def explorer_children_view(request):
    parent_type = request.GET.get('parent_type')
    parent_id = request.GET.get('parent_id')
    
    tag_ids_param = request.GET.get('tags')
    exclude_tag_ids_param = request.GET.get('exclude_tags')
    untagged_param = request.GET.get('untagged')
    
    def apply_tag_filters(qs):
        if tag_ids_param:
            tag_ids = [int(tid) for tid in tag_ids_param.split(',') if tid.strip().isdigit()]
            for tid in tag_ids:
                qs = qs.filter(tags__id=tid)
        if exclude_tag_ids_param:
            exclude_tag_ids = [int(tid) for tid in exclude_tag_ids_param.split(',') if tid.strip().isdigit()]
            if exclude_tag_ids:
                qs = qs.exclude(tags__id__in=exclude_tag_ids)
        if untagged_param == 'true':
            qs = qs.filter(tags__isnull=True)
        return qs.distinct()

    if parent_type == 'container':
        parent_container = get_object_or_404(WorkspaceContainer, id=parent_id)
        
        child_containers = WorkspaceContainer.objects.filter(
            parent=parent_container,
            is_archived=False
        )
        child_containers = apply_tag_filters(child_containers).order_by('order', 'title')
        
        container_ct = ContentType.objects.get_for_model(WorkspaceContainer)
        child_items = ExecutionItem.objects.filter(
            content_type=container_ct,
            object_id=parent_container.id,
            is_deleted=False,
            is_archived=False
        )
        child_items = apply_tag_filters(child_items).order_by('status', 'created_at')
        
        all_containers = WorkspaceContainer.objects.filter(is_archived=False).exclude(id=parent_container.id).order_by('title')
        
        return render(request, 'partials/explorer_nodes.html', {
            'child_containers': child_containers,
            'child_items': child_items,
            'parent_container': parent_container,
            'all_containers': all_containers,
        })
        
    elif parent_type == 'task':
        parent_task = get_object_or_404(ExecutionItem, id=parent_id)
        task_ct = ContentType.objects.get_for_model(ExecutionItem)
        
        child_items = ExecutionItem.objects.filter(
            content_type=task_ct,
            object_id=parent_task.id,
            is_deleted=False,
            is_archived=False
        )
        child_items = apply_tag_filters(child_items).order_by('status', 'created_at')
        
        all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
        
        return render(request, 'partials/explorer_nodes.html', {
            'child_items': child_items,
            'parent_task': parent_task,
            'all_containers': all_containers,
        })
        
    return HttpResponse("Invalid query", status=400)

@login_required
@require_POST
def explorer_add_child_view(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        item_type = request.POST.get('item_type', 'Task')
        parent_type = request.POST.get('parent_type')
        parent_id = request.POST.get('parent_id')
        
        if not title or not parent_type or not parent_id:
            return HttpResponse("Missing parameters", status=400)
            
        new_item = ExecutionItem(
            title=title,
            item_type=item_type,
            status='Planned',
            is_completed=False
        )
        
        if parent_type == 'container':
            parent_container = get_object_or_404(WorkspaceContainer, id=parent_id)
            if parent_container:
                new_item.content_type = ContentType.objects.get_for_model(WorkspaceContainer)
                new_item.object_id = parent_container.id
                new_item.domain = parent_container.domain
                new_item.para_category = parent_container.para_category
        elif parent_type == 'task':
            parent_task = get_object_or_404(ExecutionItem, id=parent_id)
            if parent_task:
                new_item.content_type = ContentType.objects.get_for_model(ExecutionItem)
                new_item.object_id = parent_task.id
                new_item.domain = parent_task.domain
                new_item.para_category = parent_task.para_category
            
        new_item.save()
        
        if request.headers.get('HX-Request'):
            # Trigger custom HTMX event to reload the child node dynamically!
            response = HttpResponse(f"<span class='text-xs text-emerald-400'>✓ Added!</span>")
            response['HX-Trigger'] = f"reload-node-{parent_type}-{parent_id}"
            return response
            
        return redirect('explorer')
    return redirect('explorer')

@login_required
@require_POST
def explorer_move_view(request):
    if request.method == 'POST':
        node_type = request.POST.get('node_type')
        node_id = request.POST.get('node_id')
        new_parent_id = request.POST.get('new_parent_id')
        
        if not node_type or not node_id:
            return HttpResponse("Missing parameters", status=400)
            
        if node_type == 'container':
            container = get_object_or_404(WorkspaceContainer, id=node_id)
            if new_parent_id:
                new_parent = get_object_or_404(WorkspaceContainer, id=new_parent_id)
                if new_parent.id == container.id:
                    messages.error(request, "Cannot set container as parent of itself.")
                else:
                    container.parent = new_parent
                    try:
                        container.save()
                    except ValidationError as e:
                        messages.error(request, f"Error: {e.messages[0]}")
            else:
                container.parent = None
                try:
                    container.save()
                except ValidationError as e:
                    messages.error(request, f"Error: {e.messages[0]}")
            
        elif node_type == 'item':
            item = get_object_or_404(ExecutionItem, id=node_id)
            if new_parent_id:
                new_parent = get_object_or_404(WorkspaceContainer, id=new_parent_id)
                item.content_type = ContentType.objects.get_for_model(WorkspaceContainer)
                item.object_id = new_parent.id
                if item.status == 'Inbox':
                    item.status = 'Planned'
                item.save()
            else:
                item.content_type = None
                item.object_id = None
                item.status = 'Inbox'
                item.save()
            
        return redirect('explorer')
    return redirect('explorer')

@login_required
def explorer_edit_view(request, node_type, node_id):
    if node_type == 'container':
        container = get_object_or_404(WorkspaceContainer, id=node_id)
        if request.method == 'POST':
            container.title = request.POST.get('title', container.title)
            container.container_type = request.POST.get('container_type', container.container_type)
            
            dom_id = request.POST.get('domain_id')
            if dom_id:
                dom_cat = DomainCategory.objects.filter(id=dom_id).first()
                if dom_cat:
                    container.domain = dom_cat
            else:
                container.domain = None
                
            container.para_category = request.POST.get('para_category', container.para_category)
            
            container.priority = request.POST.get('priority', container.priority)
            container.urgency = request.POST.get('urgency', container.urgency)
            
            # Dates and cascading
            from django.utils.dateparse import parse_datetime, parse_date
            from django.utils.timezone import make_aware, is_naive
            import datetime
            
            start_str = request.POST.get('start_date', '').strip()
            end_str = request.POST.get('end_date', '').strip()
            due_str = request.POST.get('due_date', '').strip()
            
            def parse_dt(s):
                if not s: return None
                dt = parse_datetime(s)
                if not dt:
                    d = parse_date(s)
                    if d:
                        dt = make_aware(datetime.datetime.combine(d, datetime.time.min))
                elif is_naive(dt):
                    dt = make_aware(dt)
                return dt
                
            p_start = parse_dt(start_str)
            p_end = parse_dt(end_str)
            p_due = parse_dt(due_str)
            
            container.start_date = p_start
            container.end_date = p_end
            container.due_date = p_due
            
            # Reparenting
            parent_id_str = request.POST.get('parent_id')
            if parent_id_str == 'none':
                container.parent = None
            elif parent_id_str and parent_id_str.isdigit():
                new_parent = WorkspaceContainer.objects.filter(id=int(parent_id_str)).first()
                if new_parent and new_parent.id != container.id:
                    container.parent = new_parent
                    
            try:
                container.save()
            except ValidationError as e:
                messages.error(request, f"Error: {e.messages[0]}")
                return redirect('explorer-edit', node_type='container', node_id=container.id)
                
            # Perform cascading
            respect_existing = request.POST.get('respect_child_dates') == 'on'
            _cascade_container_dates(container, p_start, p_end, p_due, respect_existing)
            
            # Tags
            tag_ids = request.POST.getlist('tags')
            if tag_ids:
                container.tags.set(Tag.objects.filter(id__in=tag_ids))
            else:
                container.tags.clear()
                
            return redirect('explorer')
            
        domains = DomainCategory.objects.all().order_by('name')
        paras = [choice[0] for choice in ExecutionItem.PARA_CATEGORIES]
        types = ['Epic', 'Project', 'Specialization', 'Course', 'Module']
        all_containers = WorkspaceContainer.objects.exclude(id=container.id).order_by('title')
        all_tags = Tag.objects.all().order_by('name')
        
        settings = AppSettings.get_solo()
        
        return render(request, 'explorer_edit.html', {
            'container': container,
            'node_type': node_type,
            'domains': domains,
            'paras': paras,
            'types': types,
            'all_containers': all_containers,
            'all_tags': all_tags,
            'respect_child_dates_default': settings.respect_child_dates_by_default,
        })
        
    elif node_type == 'item':
        item = get_object_or_404(ExecutionItem, id=node_id)
        if request.method == 'POST':
            item.title = request.POST.get('title', item.title)
            item.item_type = request.POST.get('item_type', item.item_type)
            item.status = request.POST.get('status', item.status)
            if item.status == 'Completed':
                item.is_completed = True
            else:
                item.is_completed = False
            item.priority = request.POST.get('priority', item.priority)
            item.urgency = request.POST.get('urgency', item.urgency)
            
            dom_id = request.POST.get('domain_id')
            if dom_id:
                dom_cat = DomainCategory.objects.filter(id=dom_id).first()
                if dom_cat:
                    item.domain = dom_cat
            else:
                item.domain = None
                
            item.para_category = request.POST.get('para_category', item.para_category)
            
            # 1. Human readable duration estimate string
            duration = request.POST.get('duration_estimate')
            if duration:
                # Using our dynamic parser
                secs = parse_duration_to_seconds(duration)
                item.duration_estimate = max(1, secs // 60)
            
            # 2. Human readable extra time actual seconds to add
            extra_time = request.POST.get('extra_actual_time')
            if extra_time:
                # Add parsed seconds to current extra_actual_seconds
                item.extra_actual_seconds += parse_duration_to_seconds(extra_time)
                
            # 3. Start, End, Due dates
            start_val = request.POST.get('start_date')
            end_val = request.POST.get('end_date')
            due_val = request.POST.get('due_date')
            
            item.start_date = parse_datetime_input_tz(start_val)
            item.end_date = parse_datetime_input_tz(end_val)
            item.due_date = parse_datetime_input_tz(due_val)
            
            # 4. Fuzzy scheduling
            item.fuzzy_timeframe = request.POST.get('fuzzy_timeframe') or None
            item.save()
            
            # 5. Recurrence Config
            recur_freq = request.POST.get('recurrence_frequency')
            if recur_freq:
                custom_count = request.POST.get('custom_times_count')
                custom_period = request.POST.get('custom_period')
                
                RecurringConfig.objects.update_or_create(
                    execution_item=item,
                    defaults={
                        'frequency': recur_freq,
                        'custom_times_count': int(custom_count) if custom_count else None,
                        'custom_period': custom_period if custom_period else None,
                    }
                )
            else:
                RecurringConfig.objects.filter(execution_item=item).delete()
                
            # 6. Notion Integration link
            notion_url = request.POST.get('notion_page_url')
            if notion_url:
                NotionIntegration.objects.update_or_create(
                    execution_item=item,
                    defaults={'notion_page_url': notion_url}
                )
            else:
                NotionIntegration.objects.filter(execution_item=item).delete()
                
            # 7. Tags
            tag_ids = request.POST.getlist('tags')
            if tag_ids:
                item.tags.set(Tag.objects.filter(id__in=tag_ids))
            else:
                item.tags.clear()
                
            return redirect('explorer')
            
        domains = DomainCategory.objects.all().order_by('name')
        paras = [choice[0] for choice in ExecutionItem.PARA_CATEGORIES]
        statuses = [choice[0] for choice in ExecutionItem.STATUS_CHOICES]
        priorities = [choice[0] for choice in ExecutionItem.PRIORITY_CHOICES]
        urgencies = [choice[0] for choice in ExecutionItem.URGENCY_CHOICES]
        types = [choice[0] for choice in ExecutionItem.ITEM_TYPES]
        all_tags = Tag.objects.all().order_by('name')
        
        # Get related configs
        recurrence = RecurringConfig.objects.filter(execution_item=item).first()
        notion = NotionIntegration.objects.filter(execution_item=item).first()
        
        return render(request, 'explorer_edit.html', {
            'item': item,
            'node_type': node_type,
            'domains': domains,
            'paras': paras,
            'statuses': statuses,
            'priorities': priorities,
            'urgencies': urgencies,
            'types': types,
            'recurrence': recurrence,
            'notion': notion,
            'all_tags': all_tags,
            'fuzzy_timeframes': ['Today', 'Tomorrow', 'Weekend', 'Week', 'Month'],
            'frequencies': ['Daily', 'Weekly', 'Monthly', 'Quarterly', 'Annually', 'Custom'],
        })
        
    return HttpResponse("Invalid node type", status=400)

@login_required
def explorer_bulk_action_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        item_ids = request.POST.getlist('selected_items')
        container_ids = request.POST.getlist('selected_containers')
        
        if not action:
            return HttpResponse("Missing action", status=400)
            
        if action == 'archive':
            ExecutionItem.objects.filter(id__in=item_ids).update(is_archived=True)
            WorkspaceContainer.objects.filter(id__in=container_ids).update(is_archived=True)
            messages.success(request, f"Bulk archived selected items.")
        elif action == 'delete':
            ExecutionItem.objects.filter(id__in=item_ids).update(is_deleted=True)
            WorkspaceContainer.objects.filter(id__in=container_ids).update(is_archived=True)
            messages.success(request, f"Bulk soft-deleted selected execution items & archived containers.")
            
        return redirect('explorer')
    return redirect('explorer')

def _cascade_container_dates(container, start, end, due, respect_existing=False):
    from django.contrib.contenttypes.models import ContentType
    
    # 1. Recurse down children containers
    for child_c in container.children.filter(is_archived=False):
        if not respect_existing or (not child_c.start_date and not child_c.end_date and not child_c.due_date):
            if not respect_existing:
                child_c.start_date = start
                child_c.end_date = end
                child_c.due_date = due
            else:
                if start and not child_c.start_date: child_c.start_date = start
                if end and not child_c.end_date: child_c.end_date = end
                if due and not child_c.due_date: child_c.due_date = due
            child_c.save()
        _cascade_container_dates(child_c, start, end, due, respect_existing)
        
    # 2. Recurse down execution items linked to this container
    container_ct = ContentType.objects.get_for_model(WorkspaceContainer)
    items = ExecutionItem.objects.filter(content_type=container_ct, object_id=container.id, is_deleted=False)
    for item in items:
        _cascade_item_dates(item, start, end, due, respect_existing)

def _cascade_item_dates(item, start, end, due, respect_existing=False):
    from django.contrib.contenttypes.models import ContentType
    
    if not respect_existing or (not item.start_date and not item.end_date and not item.due_date):
        if not respect_existing:
            item.start_date = start
            item.end_date = end
            item.due_date = due
        else:
            if start and not item.start_date: item.start_date = start
            if end and not item.end_date: item.end_date = end
            if due and not item.due_date: item.due_date = due
        item.save()
        
    item_ct = ContentType.objects.get_for_model(ExecutionItem)
    subtasks = ExecutionItem.objects.filter(content_type=item_ct, object_id=item.id, is_deleted=False)
    for sub in subtasks:
        _cascade_item_dates(sub, start, end, due, respect_existing)

def parse_datetime_input_tz(val):
    from ..context_processors import parse_datetime_input
    return parse_datetime_input(val)

@login_required
@require_POST
def container_check_bounds_view(request, container_id):
    """
    Checks if setting proposed start/end/due dates on a container
    will conflict with any of its child containers or tasks.
    """
    from django.utils.dateparse import parse_datetime, parse_date
    from django.utils.timezone import make_aware, is_naive
    
    container = None
    if container_id > 0:
        container = get_object_or_404(WorkspaceContainer, id=container_id)
        
    start_str = request.POST.get('start_date', '').strip()
    end_str = request.POST.get('end_date', '').strip()
    due_str = request.POST.get('due_date', '').strip()
    
    def parse_input_datetime(s):
        if not s:
            return None
        dt = parse_datetime(s)
        if not dt:
            d = parse_date(s)
            if d:
                dt = make_aware(timezone.datetime.combine(d, timezone.datetime.min.time()))
        else:
            if is_naive(dt):
                dt = make_aware(dt)
        return dt

    proposed_start = parse_input_datetime(start_str)
    proposed_end = parse_input_datetime(end_str)
    proposed_due = parse_input_datetime(due_str)
    
    conflicts = []
    
    if container:
        containers, items = _get_recursive_children_containers_and_items(container)
        
        all_items = list(items)
        for item in items:
            all_items.extend(_get_recursive_subtasks_for_item(item))
            
        # Check containers
        for c in containers:
            c_conflicts = []
            if proposed_start and c.start_date and c.start_date < proposed_start:
                c_conflicts.append(f"Start date ({c.start_date.strftime('%Y-%m-%d')}) is before proposed start.")
            if proposed_end and c.end_date and c.end_date > proposed_end:
                c_conflicts.append(f"End date ({c.end_date.strftime('%Y-%m-%d')}) is after proposed end.")
            if proposed_due and c.due_date and c.due_date > proposed_due:
                c_conflicts.append(f"Due date ({c.due_date.strftime('%Y-%m-%d')}) is after proposed due.")
                
            if c_conflicts:
                conflicts.append({
                    'name': c.title,
                    'type': c.container_type,
                    'messages': c_conflicts
                })
                
        # Check tasks
        for item in all_items:
            i_conflicts = []
            if proposed_start:
                if item.start_date and item.start_date < proposed_start:
                    i_conflicts.append(f"Start date ({item.start_date.strftime('%Y-%m-%d')}) is before proposed start.")
                if item.due_date and item.due_date < proposed_start:
                    i_conflicts.append(f"Due date ({item.due_date.strftime('%Y-%m-%d')}) is before proposed start.")
            if proposed_end and item.end_date and item.end_date > proposed_end:
                i_conflicts.append(f"End date ({item.end_date.strftime('%Y-%m-%d')}) is after proposed end.")
            if proposed_due and item.due_date and item.due_date > proposed_due:
                i_conflicts.append(f"Due date ({item.due_date.strftime('%Y-%m-%d')}) is after proposed due.")
                
            if i_conflicts:
                conflicts.append({
                    'name': item.title,
                    'type': item.item_type,
                    'messages': i_conflicts
                })
                
    return JsonResponse({'conflicts': conflicts})

def _get_recursive_children_containers_and_items(container):
    from django.contrib.contenttypes.models import ContentType
    container_ct = ContentType.objects.get_for_model(WorkspaceContainer)
    
    children_containers = list(container.children.filter(is_archived=False))
    items = list(ExecutionItem.objects.filter(content_type=container_ct, object_id=container.id, is_deleted=False))
    
    for child in container.children.filter(is_archived=False):
        child_containers, child_items = _get_recursive_children_containers_and_items(child)
        children_containers.extend(child_containers)
        items.extend(child_items)
        
    return children_containers, items

def _get_recursive_subtasks_for_item(item):
    from django.contrib.contenttypes.models import ContentType
    item_ct = ContentType.objects.get_for_model(ExecutionItem)
    
    subtasks = list(ExecutionItem.objects.filter(content_type=item_ct, object_id=item.id, is_deleted=False))
    all_subtasks = list(subtasks)
    
    for sub in subtasks:
        all_subtasks.extend(_get_recursive_subtasks_for_item(sub))
        
    return all_subtasks

