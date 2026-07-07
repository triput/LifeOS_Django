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
from .explorer import parse_datetime_input_tz


@login_required
def explorer_grid_view(request):
    """
    Renders the spreadsheet-style grid editor for the backlog tree.
    """
    unprepared_only = request.GET.get('unprepared_only') == 'true'
    
    root_containers = WorkspaceContainer.objects.filter(
        parent=None,
        is_archived=False
    ).order_by('container_type', 'title')
    
    orphan_items = ExecutionItem.objects.filter(
        content_type=None,
        is_deleted=False,
        is_archived=False
    ).order_by('status', '-created_at')
    
    if unprepared_only:
        from django.db.models import Q
        root_containers = root_containers.filter(
            Q(domain__isnull=True) | (Q(priority='Medium') & Q(urgency='Normal'))
        )
        orphan_items = orphan_items.filter(
            Q(duration_estimate=30) | Q(domain__isnull=True) | (Q(priority='Medium') & Q(urgency='Normal'))
        )
        
    all_domains = DomainCategory.objects.all().order_by('name')
    all_tags = Tag.objects.all().order_by('name')
    
    # Pre-fetch all containers for parent selectors
    all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
    
    context = {
        'root_containers': root_containers,
        'orphan_items': orphan_items,
        'all_domains': all_domains,
        'all_tags': all_tags,
        'all_containers': all_containers,
        'unprepared_only': unprepared_only,
    }
    return render(request, 'explorer_grid.html', context)

@login_required
def explorer_grid_children_view(request):
    """
    Lazy-loads children in the grid layout.
    """
    parent_type = request.GET.get('parent_type')
    parent_id = request.GET.get('parent_id')
    unprepared_only = request.GET.get('unprepared_only') == 'true'
    
    # Receive depth to propagate to children
    depth = int(request.GET.get('depth', '0'))
    child_depth = depth + 1
    
    all_domains = DomainCategory.objects.all().order_by('name')
    all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
    
    if parent_type == 'container':
        parent_container = get_object_or_404(WorkspaceContainer, id=parent_id)
        
        child_containers = WorkspaceContainer.objects.filter(
            parent=parent_container,
            is_archived=False
        ).order_by('order', 'title')
        
        container_ct = ContentType.objects.get_for_model(WorkspaceContainer)
        child_items = ExecutionItem.objects.filter(
            content_type=container_ct,
            object_id=parent_container.id,
            is_deleted=False,
            is_archived=False
        ).order_by('status', 'created_at')
        
        if unprepared_only:
            from django.db.models import Q
            child_containers = child_containers.filter(
                Q(domain__isnull=True) | (Q(priority='Medium') & Q(urgency='Normal'))
            )
            child_items = child_items.filter(
                Q(duration_estimate=30) | Q(domain__isnull=True) | (Q(priority='Medium') & Q(urgency='Normal'))
            )
            
        return render(request, 'partials/grid_nodes.html', {
            'child_containers': child_containers,
            'child_items': child_items,
            'parent_container': parent_container,
            'all_domains': all_domains,
            'all_containers': all_containers,
            'all_tags': Tag.objects.all().order_by('name'),
            'depth': child_depth,
            'unprepared_only': unprepared_only,
        })
        
    elif parent_type == 'task':
        parent_task = get_object_or_404(ExecutionItem, id=parent_id)
        task_ct = ContentType.objects.get_for_model(ExecutionItem)
        
        child_items = ExecutionItem.objects.filter(
            content_type=task_ct,
            object_id=parent_task.id,
            is_deleted=False,
            is_archived=False
        ).order_by('status', 'created_at')
        
        if unprepared_only:
            from django.db.models import Q
            child_items = child_items.filter(
                Q(duration_estimate=30) | Q(domain__isnull=True) | (Q(priority='Medium') & Q(urgency='Normal'))
            )
            
        return render(request, 'partials/grid_nodes.html', {
            'child_items': child_items,
            'parent_task': parent_task,
            'all_domains': all_domains,
            'all_containers': all_containers,
            'all_tags': Tag.objects.all().order_by('name'),
            'depth': child_depth,
            'unprepared_only': unprepared_only,
        })
        
    return HttpResponse("Invalid query", status=400)

@login_required
@require_POST
def explorer_grid_save_field_view(request):
    """
    Handles auto-saving updates from individual inline inputs in the grid.
    """
    model_type = request.POST.get('model_type') # 'container' or 'item'
    model_id = request.POST.get('model_id')
    field = request.POST.get('field')
    
    if not model_type or not model_id or not field:
        return HttpResponse("Missing fields", status=400)
        
    key = f"{field}_{model_type}_{model_id}"
    
    if model_type == 'container':
        obj = get_object_or_404(WorkspaceContainer, id=model_id)
    elif model_type == 'item':
        obj = get_object_or_404(ExecutionItem, id=model_id)
    else:
        return HttpResponse("Invalid model type", status=400)
        
    try:
        if field == 'tags':
            tag_ids = request.POST.getlist(key)
        else:
            value = request.POST.get(key, '').strip()
            
        if field == 'title':
            if not value:
                return HttpResponse("Title cannot be empty", status=400)
            obj.title = value
        elif field == 'container_type':
            obj.container_type = value
        elif field == 'item_type':
            obj.item_type = value
        elif field == 'status':
            obj.status = value
        elif field == 'priority':
            obj.priority = value
        elif field == 'urgency':
            obj.urgency = value
        elif field == 'domain':
            if value == '' or value == 'None':
                obj.domain = None
            else:
                obj.domain = get_object_or_404(DomainCategory, id=value)
        elif field == 'start_date':
            obj.start_date = value if value else None
        elif field == 'due_date':
            obj.due_date = value if value else None
        elif field == 'tags':
            tag_ids = [tid for tid in tag_ids if tid.strip() and tid != 'None' and tid != '']
            if not tag_ids:
                obj.tags.clear()
            else:
                obj.tags.set(Tag.objects.filter(id__in=tag_ids))
        else:
            return HttpResponse(f"Unsupported field: {field}", status=400)
            
        obj.save()
        
        if field == 'tags':
            all_domains = DomainCategory.objects.all().order_by('name')
            all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
            all_tags = Tag.objects.all().order_by('name')
            
            # depth needs to be passed back
            depth = int(request.POST.get('depth', '0'))
            
            context = {
                'all_domains': all_domains,
                'all_containers': all_containers,
                'all_tags': all_tags,
                'depth': depth,
                'open_tag_dropdown': True,
            }
            if model_type == 'container':
                context['child'] = obj
                context['is_container'] = True
            else:
                context['item'] = obj
                context['is_container'] = False
                
            return render(request, 'partials/grid_row.html', context)
            
        return HttpResponse(status=200)
    except Exception as e:
        return HttpResponse(f"Save failed: {str(e)}", status=500)

@login_required
@require_POST
def explorer_grid_add_row_view(request):
    """
    Creates a new placeholder record in the DB and returns its grid row HTML.
    """
    parent_type = request.POST.get('parent_type', 'root') # 'container', 'task', or 'root'
    parent_id = request.POST.get('parent_id')
    row_type = request.POST.get('row_type', 'Task') # 'Task', 'WorkspaceContainer'
    
    # Indentation/depth level
    depth = int(request.POST.get('depth', '0'))
    child_depth = depth + 1
    
    all_domains = DomainCategory.objects.all().order_by('name')
    all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
    
    if row_type == 'WorkspaceContainer':
        container = WorkspaceContainer.objects.create(
            title="New Container",
            container_type="Project",
            para_category="Projects"
        )
        if parent_type == 'container' and parent_id:
            parent_container = get_object_or_404(WorkspaceContainer, id=parent_id)
            container.parent = parent_container
            # Inherit domain
            container.domain = parent_container.domain
            container.save()
            
        return render(request, 'partials/grid_row.html', {
            'child': container,
            'is_container': True,
            'depth': child_depth if parent_type != 'root' else 0,
            'all_domains': all_domains,
            'all_containers': all_containers,
            'all_tags': Tag.objects.all().order_by('name'),
        })
        
    else: # ExecutionItem
        item = ExecutionItem.objects.create(
            title="New Task",
            item_type="Task",
            status="Inbox"
        )
        if parent_type == 'container' and parent_id:
            container_ct = ContentType.objects.get_for_model(WorkspaceContainer)
            item.content_type = container_ct
            item.object_id = parent_id
            # Inherit domain
            parent_container = get_object_or_404(WorkspaceContainer, id=parent_id)
            item.domain = parent_container.domain
            item.save()
        elif parent_type == 'task' and parent_id:
            task_ct = ContentType.objects.get_for_model(ExecutionItem)
            item.content_type = task_ct
            item.object_id = parent_id
            # Inherit domain
            parent_task = get_object_or_404(ExecutionItem, id=parent_id)
            item.domain = parent_task.domain
            item.save()
            
        return render(request, 'partials/grid_row.html', {
            'item': item,
            'is_container': False,
            'depth': child_depth if parent_type != 'root' else 0,
            'all_domains': all_domains,
            'all_containers': all_containers,
            'all_tags': Tag.objects.all().order_by('name'),
        })

@login_required
@require_POST
def explorer_grid_create_tag_view(request):
    """
    Creates a new Tag on the fly, assigns it to the specified item/container,
    and returns the re-rendered row HTML.
    """
    model_type = request.POST.get('model_type')
    model_id = request.POST.get('model_id')
    tag_name = request.POST.get('tag_name', '').strip()
    
    if not model_type or not model_id or not tag_name:
        return HttpResponse("Missing fields", status=400)
        
    # Generate random color for new tags
    import random
    colors = ['#FF5733', '#33FF57', '#3357FF', '#F3FF33', '#FF33F3', '#33FFF3', '#FFA833', '#9966CC', '#50C878', '#0F52BA']
    color = random.choice(colors)
    
    tag, created = Tag.objects.get_or_create(name=tag_name, defaults={'color': color})
    
    if model_type == 'container':
        obj = get_object_or_404(WorkspaceContainer, id=model_id)
        is_container = True
    else:
        obj = get_object_or_404(ExecutionItem, id=model_id)
        is_container = False
        
    # Assign the tag to the object
    obj.tags.add(tag)
    
    all_domains = DomainCategory.objects.all().order_by('name')
    all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
    all_tags = Tag.objects.all().order_by('name')
    
    depth = int(request.POST.get('depth', '0'))
    
    context = {
        'all_domains': all_domains,
        'all_containers': all_containers,
        'all_tags': all_tags,
        'depth': depth,
    }
    if is_container:
        context['child'] = obj
        context['is_container'] = True
    else:
        context['item'] = obj
        context['is_container'] = False
        
    # We want to open the dropdown again on load, so we pass a context variable
    context['open_tag_dropdown'] = True
    
    return render(request, 'partials/grid_row.html', context)

@login_required
def explorer_grid_modal_view(request, model_type, model_id):
    """
    Renders the right-side detail edit drawer for a container or task (GET),
    and processes the update to save changes and replace the grid row (POST).
    """
    if model_type == 'container':
        obj = get_object_or_404(WorkspaceContainer, id=model_id)
        is_container = True
    else:
        obj = get_object_or_404(ExecutionItem, id=model_id)
        is_container = False

    if request.method == 'POST':
        # 1. Update general fields
        obj.title = request.POST.get('title', obj.title).strip()
        
        dom_id = request.POST.get('domain_id')
        if dom_id:
            dom_cat = DomainCategory.objects.filter(id=dom_id).first()
            if dom_cat:
                obj.domain = dom_cat
        else:
            obj.domain = None
            
        obj.priority = request.POST.get('priority', obj.priority)
        obj.urgency = request.POST.get('urgency', obj.urgency)

        if is_container:
            obj.container_type = request.POST.get('container_type', obj.container_type)
            obj.para_category = request.POST.get('para_category', obj.para_category) or None
            
            # Academy fields
            cert_id = request.POST.get('certification_id')
            if cert_id:
                obj.certification = Certification.objects.filter(id=cert_id).first()
            else:
                obj.certification = None
            obj.credits_earned = request.POST.get('credits_earned', obj.credits_earned) or 0
            
            # Reparenting logic
            parent_id_str = request.POST.get('parent_id')
            if parent_id_str == 'none':
                obj.parent = None
            elif parent_id_str and parent_id_str.isdigit():
                new_parent = WorkspaceContainer.objects.filter(id=int(parent_id_str)).first()
                if new_parent and new_parent.id != obj.id:
                    obj.parent = new_parent
            
            try:
                obj.save()
            except ValidationError as e:
                return HttpResponse(f"Validation Error: {e.messages[0]}", status=400)
        else:
            obj.item_type = request.POST.get('item_type', obj.item_type)
            obj.status = request.POST.get('status', obj.status)
            obj.para_category = request.POST.get('para_category', obj.para_category) or None
            
            # Completion sync is handled in ExecutionItem.save()
            
            # Human readable duration estimate string
            duration = request.POST.get('duration_estimate')
            if duration:
                secs = parse_duration_to_seconds(duration)
                obj.duration_estimate = max(1, secs // 60)
            
            # Extra time actual logging
            extra_time = request.POST.get('extra_actual_time')
            if extra_time:
                obj.extra_actual_seconds += parse_duration_to_seconds(extra_time)
                
            # Dates
            start_val = request.POST.get('start_date')
            due_val = request.POST.get('due_date')
            obj.start_date = parse_datetime_input_tz(start_val)
            obj.due_date = parse_datetime_input_tz(due_val)
            
            # Fuzzy timeframe
            obj.fuzzy_timeframe = request.POST.get('fuzzy_timeframe') or None
            
            obj.save()
            
            # Notion Integration link
            notion_url = request.POST.get('notion_page_url')
            if notion_url:
                NotionIntegration.objects.update_or_create(
                    execution_item=obj,
                    defaults={'notion_page_url': notion_url}
                )
            else:
                NotionIntegration.objects.filter(execution_item=obj).delete()

        # Tags
        tag_ids = request.POST.getlist('tags')
        if tag_ids:
            obj.tags.set(Tag.objects.filter(id__in=tag_ids))
        else:
            obj.tags.clear()

        # If source is dashboard, trigger page refresh
        source = request.POST.get('source')
        if source == 'dashboard':
            response = HttpResponse()
            response['HX-Refresh'] = 'true'
            return response

        # Render updated row with context + out-of-band swap to clear modal
        all_domains = DomainCategory.objects.all().order_by('name')
        all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
        all_tags = Tag.objects.all().order_by('name')
        
        depth = int(request.POST.get('depth', '0'))
        
        context = {
            'all_domains': all_domains,
            'all_containers': all_containers,
            'all_tags': all_tags,
            'depth': depth,
        }
        if is_container:
            context['child'] = obj
            context['is_container'] = True
        else:
            context['item'] = obj
            context['is_container'] = False
            
        rendered_row = render(request, 'partials/grid_row.html', context).content.decode('utf-8')
        
        # Out of band swap to empty the modal container (close the drawer)
        oob_close = '<div id="modal-container" hx-swap-oob="innerHTML" class="relative z-50"></div>'
        return HttpResponse(rendered_row + oob_close)

    # GET: Render detail edit drawer
    domains = DomainCategory.objects.all().order_by('name')
    paras = [choice[0] for choice in ExecutionItem.PARA_CATEGORIES]
    priorities = [choice[0] for choice in ExecutionItem.PRIORITY_CHOICES]
    urgencies = [choice[0] for choice in ExecutionItem.URGENCY_CHOICES]
    all_tags = Tag.objects.all().order_by('name')
    
    context = {
        'obj': obj,
        'model_type': model_type,
        'is_container': is_container,
        'domains': domains,
        'paras': paras,
        'priorities': priorities,
        'urgencies': urgencies,
        'all_tags': all_tags,
        'depth': request.GET.get('depth', '0'),
        'source': request.GET.get('source', ''),
    }

    if is_container:
        context['types'] = ['Epic', 'Project', 'Specialization', 'Course', 'Module']
        context['all_containers'] = WorkspaceContainer.objects.exclude(id=obj.id).order_by('title')
        context['certifications'] = Certification.objects.all().order_by('title')
    else:
        context['types'] = [choice[0] for choice in ExecutionItem.ITEM_TYPES]
        context['statuses'] = [choice[0] for choice in ExecutionItem.STATUS_CHOICES]
        # Duration string representation helper
        context['duration_estimate_str'] = format_seconds_to_duration(obj.duration_estimate * 60)
        
        # Try finding recurrence
        recur = getattr(obj, 'recurrence', None)
        if recur:
            context['recurrence'] = recur
            
        # Try finding notion link
        notion = getattr(obj, 'notion_link', None)
        if notion:
            context['notion_page_url'] = notion.notion_page_url

    return render(request, 'partials/grid_modal.html', context)

@login_required
@require_POST
def explorer_grid_bulk_action_view(request):
    """
    Applies selected bulk actions (status shift, reparenting, tagging, scheduling, 
    archiving, deleting) to a checklist of checked items and containers in the grid.
    """
    action = request.POST.get('action')
    selected_items = request.POST.getlist('selected_items')
    selected_containers = request.POST.getlist('selected_containers')
    
    if not selected_items and not selected_containers:
        messages.warning(request, "No items or containers selected.")
        response = HttpResponse()
        response['HX-Refresh'] = 'true'
        return response

    if action == 'archive':
        ExecutionItem.objects.filter(id__in=selected_items).update(is_archived=True)
        WorkspaceContainer.objects.filter(id__in=selected_containers).update(is_archived=True)
        messages.success(request, f"Bulk archived {len(selected_items) + len(selected_containers)} items.")

    elif action == 'delete':
        ExecutionItem.objects.filter(id__in=selected_items).update(is_deleted=True)
        WorkspaceContainer.objects.filter(id__in=selected_containers).update(is_archived=True)
        messages.success(request, f"Bulk deleted/archived {len(selected_items) + len(selected_containers)} items.")

    elif action == 'status':
        status_val = request.POST.get('bulk_status')
        if status_val:
            is_comp = (status_val == 'Completed')
            for item in ExecutionItem.objects.filter(id__in=selected_items):
                item.status = status_val
                item.is_completed = is_comp
                item.save()
            messages.success(request, f"Bulk updated status to '{status_val}' on selected tasks.")

    elif action == 'reparent':
        parent_id_str = request.POST.get('bulk_parent')
        if parent_id_str == 'none':
            WorkspaceContainer.objects.filter(id__in=selected_containers).update(parent=None)
            ExecutionItem.objects.filter(id__in=selected_items).update(content_type=None, object_id=None, status='Inbox')
            messages.success(request, "Bulk moved selected items to root backlog.")
        elif parent_id_str and parent_id_str.isdigit():
            new_parent = get_object_or_404(WorkspaceContainer, id=int(parent_id_str))
            
            # Reparent tasks
            for item in ExecutionItem.objects.filter(id__in=selected_items):
                item.content_type = ContentType.objects.get_for_model(WorkspaceContainer)
                item.object_id = new_parent.id
                if item.status == 'Inbox':
                    item.status = 'Planned'
                item.save()
                
            # Reparent containers (with cycle check)
            moved_containers = 0
            for container in WorkspaceContainer.objects.filter(id__in=selected_containers):
                if container.id == new_parent.id:
                    continue
                # Cycle check
                curr = new_parent
                cycle = False
                while curr is not None:
                    if curr.id == container.id:
                        cycle = True
                        break
                    curr = curr.parent
                if cycle:
                    continue
                container.parent = new_parent
                container.save()
                moved_containers += 1
                
            messages.success(request, f"Bulk reparented selected items under '{new_parent.title}'.")

    elif action == 'add_tag':
        tag_id = request.POST.get('bulk_tag')
        if tag_id:
            tag = get_object_or_404(Tag, id=int(tag_id))
            for item in ExecutionItem.objects.filter(id__in=selected_items):
                item.tags.add(tag)
            for container in WorkspaceContainer.objects.filter(id__in=selected_containers):
                container.tags.add(tag)
            messages.success(request, f"Bulk added tag '{tag.name}' to selected items.")

    elif action == 'remove_tag':
        tag_id = request.POST.get('bulk_tag')
        if tag_id:
            tag = get_object_or_404(Tag, id=int(tag_id))
            for item in ExecutionItem.objects.filter(id__in=selected_items):
                item.tags.remove(tag)
            for container in WorkspaceContainer.objects.filter(id__in=selected_containers):
                container.tags.remove(tag)
            messages.success(request, f"Bulk removed tag '{tag.name}' from selected items.")

    elif action == 'clear_tags':
        for item in ExecutionItem.objects.filter(id__in=selected_items):
            item.tags.clear()
        for container in WorkspaceContainer.objects.filter(id__in=selected_containers):
            container.tags.clear()
        messages.success(request, "Bulk cleared all tags from selected items.")

    elif action == 'set_dates':
        start_val = request.POST.get('bulk_start_date')
        due_val = request.POST.get('bulk_due_date')
        start_date = parse_datetime_input_tz(start_val) if start_val else None
        due_date = parse_datetime_input_tz(due_val) if due_val else None
        
        dates_to_reschedule = set()
        settings = AppSettings.get_solo()
        try:
            import zoneinfo
            user_tz = zoneinfo.ZoneInfo(settings.timezone)
        except Exception:
            import pytz
            user_tz = pytz.timezone(settings.timezone)
            
        updated_tasks = 0
        for item in ExecutionItem.objects.filter(id__in=selected_items):
            if start_val:
                item.start_date = start_date
            if due_val:
                item.due_date = due_date
            item.save()
            if item.start_date:
                dates_to_reschedule.add(item.start_date.astimezone(user_tz).date())
            updated_tasks += 1
            
        from ..scheduler import generate_schedule_for_date
        for d in dates_to_reschedule:
            generate_schedule_for_date(d)
            
        messages.success(request, f"Bulk updated dates on {updated_tasks} selected tasks.")

    elif action == 'set_fuzzy':
        fuzzy_val = request.POST.get('bulk_fuzzy_timeframe') or None
        
        dates_to_reschedule = set()
        settings = AppSettings.get_solo()
        try:
            import zoneinfo
            user_tz = zoneinfo.ZoneInfo(settings.timezone)
        except Exception:
            import pytz
            user_tz = pytz.timezone(settings.timezone)
            
        updated_tasks = 0
        for item in ExecutionItem.objects.filter(id__in=selected_items):
            item.fuzzy_timeframe = fuzzy_val
            if fuzzy_val:
                item.start_date = None
                item.due_date = None
            item.save()
            if item.start_date:
                dates_to_reschedule.add(item.start_date.astimezone(user_tz).date())
            updated_tasks += 1
            
        from ..scheduler import generate_schedule_for_date
        for d in dates_to_reschedule:
            generate_schedule_for_date(d)
            
        messages.success(request, f"Bulk updated fuzzy timeframe to '{fuzzy_val}' on {updated_tasks} tasks.")

    response = HttpResponse()
    response['HX-Refresh'] = 'true'
    return response

@login_required
def explorer_grid_bulk_save_view(request):
    """
    Handles bulk saving for all dynamically-named fields in the backlog grid layout.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
        
    updates = {}
    tag_updates = {}
    
    for key in request.POST:
        # Expected dynamic key format: {field}_{model_type}_{model_id}
        parts = key.rsplit('_', 2)
        if len(parts) == 3:
            field, model_type, model_id_str = parts
            if model_type in ('container', 'item') and model_id_str.isdigit():
                model_id = int(model_id_str)
                if field == 'tags':
                    tag_updates[(model_type, model_id)] = request.POST.getlist(key)
                else:
                    val = request.POST.get(key)
                    if val is not None:
                        if (model_type, model_id) not in updates:
                            updates[(model_type, model_id)] = {}
                        updates[(model_type, model_id)][field] = val.strip()
                        
    # Perform database bulk saves
    for (model_type, model_id), fields in updates.items():
        if model_type == 'container':
            try:
                obj = WorkspaceContainer.objects.get(id=model_id)
                for f, val in fields.items():
                    if f == 'title' and val:
                        obj.title = val
                    elif f == 'container_type':
                        obj.container_type = val
                    elif f == 'priority':
                        obj.priority = val
                    elif f == 'urgency':
                        obj.urgency = val
                    elif f == 'domain':
                        obj.domain = None if (val == '' or val == 'None') else DomainCategory.objects.filter(id=val).first()
                obj.save()
            except WorkspaceContainer.DoesNotExist:
                pass
        elif model_type == 'item':
            try:
                obj = ExecutionItem.objects.get(id=model_id)
                for f, val in fields.items():
                    if f == 'title' and val:
                        obj.title = val
                    elif f == 'item_type':
                        obj.item_type = val
                    elif f == 'status':
                        obj.status = val
                    elif f == 'priority':
                        obj.priority = val
                    elif f == 'urgency':
                        obj.urgency = val
                    elif f == 'domain':
                        obj.domain = None if (val == '' or val == 'None') else DomainCategory.objects.filter(id=val).first()
                    elif f == 'start_date':
                        obj.start_date = val if val else None
                    elif f == 'due_date':
                        obj.due_date = val if val else None
                obj.save()
            except ExecutionItem.DoesNotExist:
                pass
                
    # Update tags in bulk
    for (model_type, model_id), tag_ids in tag_updates.items():
        filtered_ids = [tid for tid in tag_ids if tid.strip() and tid != 'None']
        if model_type == 'container':
            obj = WorkspaceContainer.objects.filter(id=model_id).first()
            if obj:
                if not filtered_ids:
                    obj.tags.clear()
                else:
                    obj.tags.set(Tag.objects.filter(id__in=filtered_ids))
        elif model_type == 'item':
            obj = ExecutionItem.objects.filter(id=model_id).first()
            if obj:
                if not filtered_ids:
                    obj.tags.clear()
                else:
                    obj.tags.set(Tag.objects.filter(id__in=filtered_ids))
                    
    messages.success(request, "All grid changes synced and saved successfully!")
    return redirect('explorer-grid')

