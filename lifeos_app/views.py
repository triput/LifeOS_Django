# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/views.py
# Description: Views implementing auth, focus engine controls, and context HUD logic
# Component: Core / Views
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-26
# ==============================================================================
"""View controllers for the LifeOS application.

Contains dashboard views, HUD calculations, focus engine endpoints,
scoped workspace handlers, and authentication routes.
"""

import os
import json
from django.db import models
from django.db.models import Count, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone
from django.contrib import messages
from django.core import serializers

from .models import WorkspaceContainer, ExecutionItem, AppSettings, DomainCategory, Certification, RecurringConfig, GoogleCalendar, NotionIntegration, parse_duration_to_seconds, format_seconds_to_duration
from .telemetry import OpenMeteoAdapter, NoaaKpAdapter

def login_view(request):
    """
    Renders the login view and handles authenticated session setups.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            # Hard single-owner enforcement check on login (FR-SEC-003)
            if user.is_superuser:
                auth_login(request, user)
                return redirect('dashboard')
            else:
                form.add_error(None, "Forbidden: Only the owner account is allowed access.")
    else:
        form = AuthenticationForm()

    return render(request, 'login.html', {'form': form})


def logout_view(request):
    """
    Terminates the authenticated session and redirects.
    """
    auth_logout(request)
    return redirect('login')


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
    ).exclude(status__in=['Inbox', 'Backlog']).order_by('created_at')

    # Filter scheduled/upcoming items
    upcoming_items = ExecutionItem.objects.filter(
        is_completed=False,
        is_deleted=False,
        is_archived=False
    ).exclude(status__in=['Inbox', 'Backlog']).filter(
        models.Q(start_date__isnull=False) | 
        models.Q(due_date__isnull=False) | 
        models.Q(fuzzy_timeframe__isnull=False)
    ).order_by('due_date', 'start_date')

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


# Quick Entry View (FR-QUICK-001)
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


def clear_toast_view(request):
    return render(request, 'partials/clear_toast.html')


# Inbox Triage View (FR-INBOX-002)
def triage_view(request):
    inbox_items = ExecutionItem.objects.filter(
        status='Inbox',
        is_deleted=False,
        is_archived=False
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
        'containers': containers,
        'parent_tasks': parent_tasks,
        'domains': domains,
        'paras': paras,
        'types': types,
        'statuses': statuses,
        'priorities': priorities,
    }
    return render(request, 'triage.html', context)


def process_triage_view(request, item_id):
    if request.method == 'POST':
        item = get_object_or_404(ExecutionItem, id=item_id)
        parent_raw = request.POST.get('container')
        domain = request.POST.get('domain')
        para = request.POST.get('para')
        item_type = request.POST.get('item_type', 'Task')
        duration = request.POST.get('duration_estimate')
        priority = request.POST.get('priority', 'Medium')
        status = request.POST.get('status', 'Planned')
        
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
                item.domain_category = dom_cat.name
            except DomainCategory.DoesNotExist:
                dom_cat = DomainCategory.objects.filter(name=domain).first()
                if dom_cat:
                    item.domain = dom_cat
                    item.domain_category = dom_cat.name
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


# Settings View & Diagnostics (FR-SETTINGS-001 / FR-SETTINGS-002)
def settings_view(request):
    settings = AppSettings.get_solo()
    if request.method == 'POST':
        pomodoro = request.POST.get('pomodoro_duration')
        start_hour = request.POST.get('start_of_work_day')
        ai_sched = request.POST.get('enable_ai_scheduling') == 'on'
        
        # V3.0 Configurations
        loc_name = request.POST.get('location_name', settings.location_name)
        lat = request.POST.get('latitude')
        lon = request.POST.get('longitude')
        auto_loc = request.POST.get('auto_detect_location') == 'on'
        imperial = request.POST.get('use_imperial') == 'on'
        h24 = request.POST.get('use_24h_time') == 'on'
        tz = request.POST.get('timezone', settings.timezone)
        
        hud_env = request.POST.get('hud_env', 'ENVIRONMENTAL HUD')
        hud_domain = request.POST.get('hud_domain', 'DOMAIN VELOCITY')
        hud_para = request.POST.get('hud_para', 'PARA ALLOCATION')
        
        settings.dashboard_card_names = {
            'hud_env': hud_env,
            'hud_domain': hud_domain,
            'hud_para': hud_para,
        }

        if pomodoro:
            try:
                settings.pomodoro_duration = int(pomodoro)
            except ValueError:
                pass
        if start_hour:
            settings.start_of_work_day = start_hour
            
        settings.location_name = loc_name
        settings.auto_detect_location = auto_loc
        settings.use_imperial = imperial
        settings.use_24h_time = h24
        settings.timezone = tz
        
        if lat:
            try:
                settings.latitude = float(lat)
            except ValueError:
                pass
        else:
            settings.latitude = None
            
        if lon:
            try:
                settings.longitude = float(lon)
            except ValueError:
                pass
        else:
            settings.longitude = None

        settings.enable_ai_scheduling = ai_sched
        
        # V4.0 SLM Scheduler Settings
        pw = request.POST.get('priority_weight')
        uw = request.POST.get('urgency_weight')
        if pw:
            try: settings.priority_weight = float(pw)
            except ValueError: pass
        if uw:
            try: settings.urgency_weight = float(uw)
            except ValueError: pass
            
        slm_prov = request.POST.get('slm_provider')
        if slm_prov:
            settings.slm_provider = slm_prov
        settings.slm_endpoint = request.POST.get('slm_endpoint', settings.slm_endpoint)
        settings.slm_api_key = request.POST.get('slm_api_key', settings.slm_api_key)

        settings.save()
        messages.success(request, "Settings updated successfully!")
        return redirect('settings')
        
    domains = DomainCategory.objects.all().order_by('name')
    calendars = GoogleCalendar.objects.all().order_by('name')
    context = {
        'settings': settings,
        'domains': domains,
        'calendars': calendars,
    }
    return render(request, 'settings.html', context)


def domain_add_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '#9966CC')
        icon = request.POST.get('icon', 'folder')
        is_academy = request.POST.get('is_academy') == 'on'
        
        if name:
            DomainCategory.objects.update_or_create(
                name=name,
                defaults={'color': color, 'icon': icon, 'is_academy': is_academy}
            )
            messages.success(request, f"Domain '{name}' configured successfully!")
        return redirect('settings')
    return redirect('settings')


def domain_delete_view(request, domain_id):
    domain = get_object_or_404(DomainCategory, id=domain_id)
    name = domain.name
    domain.delete()
    messages.success(request, f"Domain '{name}' deleted successfully!")
    return redirect('settings')


def calendar_add_view(request):
    if request.method == 'POST':
        cal_id = request.POST.get('calendar_id', '').strip()
        name = request.POST.get('name', 'Primary').strip()
        if cal_id:
            GoogleCalendar.objects.create(calendar_id=cal_id, name=name)
            messages.success(request, f"Google Calendar '{name}' integrated successfully!")
        return redirect('settings')
    return redirect('settings')


def calendar_delete_view(request, cal_id):
    cal = get_object_or_404(GoogleCalendar, id=cal_id)
    name = cal.name
    cal.delete()
    messages.success(request, f"Calendar '{name}' disconnected.")
    return redirect('settings')


def backup_view(request):
    if request.method == 'POST':
        try:
            containers = WorkspaceContainer.objects.all()
            items = ExecutionItem.objects.all()
            
            combined_data = list(containers) + list(items)
            serialized = serializers.serialize('json', combined_data, indent=2)
            
            backup_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backup')
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)
                
            backup_file = os.path.join(backup_dir, f"lifeos_backup_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(backup_file, 'w') as f:
                f.write(serialized)
                
            msg = f"Backup generated: {os.path.basename(backup_file)}"
            if request.headers.get('HX-Request'):
                return render(request, 'partials/backup_status.html', {'success': True, 'msg': msg})
                
            messages.success(request, msg)
        except Exception as e:
            err_msg = f"Backup failed: {str(e)}"
            if request.headers.get('HX-Request'):
                return render(request, 'partials/backup_status.html', {'success': False, 'msg': err_msg})
            messages.error(request, err_msg)
            
        return redirect('settings')
    return redirect('settings')


# Workspace Explorer (FR-EXPLORER-001)
def explorer_view(request):
    root_containers = WorkspaceContainer.objects.filter(
        parent=None,
        is_archived=False
    ).order_by('container_type', 'title')
    
    orphan_items = ExecutionItem.objects.filter(
        content_type=None,
        is_deleted=False,
        is_archived=False
    ).order_by('status', '-created_at')
    
    all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
    
    context = {
        'root_containers': root_containers,
        'orphan_items': orphan_items,
        'all_containers': all_containers,
    }
    return render(request, 'explorer.html', context)


def explorer_children_view(request):
    parent_type = request.GET.get('parent_type')
    parent_id = request.GET.get('parent_id')
    
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
        ).order_by('status', 'created_at')
        
        all_containers = WorkspaceContainer.objects.filter(is_archived=False).order_by('title')
        
        return render(request, 'partials/explorer_nodes.html', {
            'child_items': child_items,
            'parent_task': parent_task,
            'all_containers': all_containers,
        })
        
    return HttpResponse("Invalid query", status=400)


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
            new_item.content_type = ContentType.objects.get_for_model(WorkspaceContainer)
            new_item.object_id = parent_container.id
            new_item.domain_category = parent_container.domain_category
            new_item.para_category = parent_container.para_category
        elif parent_type == 'task':
            parent_task = get_object_or_404(ExecutionItem, id=parent_id)
            new_item.content_type = ContentType.objects.get_for_model(ExecutionItem)
            new_item.object_id = parent_task.id
            new_item.domain_category = parent_task.domain_category
            new_item.para_category = parent_task.para_category
            
        new_item.save()
        
        if request.headers.get('HX-Request'):
            # Trigger custom HTMX event to reload the child node dynamically!
            response = HttpResponse(f"<span class='text-xs text-emerald-400'>✓ Added!</span>")
            response['HX-Trigger'] = f"reload-node-{parent_type}-{parent_id}"
            return response
            
        return redirect('explorer')
    return redirect('explorer')


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
                    container.save()
            else:
                container.parent = None
                container.save()
            
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


def parse_datetime_input_tz(val):
    if not val:
        return None
    from django.utils.dateparse import parse_datetime
    from django.utils import timezone
    dt = parse_datetime(val)
    if dt and timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def explorer_edit_view(request, node_type, node_id):
    if node_type == 'container':
        container = get_object_or_404(WorkspaceContainer, id=node_id)
        if request.method == 'POST':
            container.title = request.POST.get('title', container.title)
            container.container_type = request.POST.get('container_type', container.container_type)
            
            dom_name = request.POST.get('domain_category')
            if dom_name:
                dom_cat = DomainCategory.objects.filter(name=dom_name).first()
                if dom_cat:
                    container.domain = dom_cat
                    container.domain_category = dom_cat.name
            else:
                container.domain = None
                container.domain_category = ''
                
            container.para_category = request.POST.get('para_category', container.para_category)
            container.save()
            return redirect('explorer')
            
        domains = DomainCategory.objects.all().order_by('name')
        paras = [choice[0] for choice in ExecutionItem.PARA_CATEGORIES]
        types = ['Epic', 'Project', 'Specialization', 'Course', 'Module']
        
        return render(request, 'explorer_edit.html', {
            'container': container,
            'node_type': node_type,
            'domains': domains,
            'paras': paras,
            'types': types,
        })
        
    elif node_type == 'item':
        item = get_object_or_404(ExecutionItem, id=node_id)
        if request.method == 'POST':
            item.title = request.POST.get('title', item.title)
            item.item_type = request.POST.get('item_type', item.item_type)
            item.status = request.POST.get('status', item.status)
            item.priority = request.POST.get('priority', item.priority)
            
            dom_name = request.POST.get('domain_category')
            if dom_name:
                dom_cat = DomainCategory.objects.filter(name=dom_name).first()
                if dom_cat:
                    item.domain = dom_cat
                    item.domain_category = dom_cat.name
            else:
                item.domain = None
                item.domain_category = ''
                
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
                
            return redirect('explorer')
            
        domains = DomainCategory.objects.all().order_by('name')
        paras = [choice[0] for choice in ExecutionItem.PARA_CATEGORIES]
        statuses = [choice[0] for choice in ExecutionItem.STATUS_CHOICES]
        priorities = [choice[0] for choice in ExecutionItem.PRIORITY_CHOICES]
        types = [choice[0] for choice in ExecutionItem.ITEM_TYPES]
        
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
            'types': types,
            'recurrence': recurrence,
            'notion': notion,
            'fuzzy_timeframes': ['Today', 'Tomorrow', 'Weekend', 'Week', 'Month'],
            'frequencies': ['Daily', 'Weekly', 'Monthly', 'Quarterly', 'Annually', 'Custom'],
        })
        
    return HttpResponse("Invalid node type", status=400)


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


# Interactive Analytics Dashboard (FR-ANALYTICS-001)
def analytics_view(request):
    domain_time = ExecutionItem.objects.filter(
        is_deleted=False
    ).values('domain_category').annotate(
        seconds=Sum('time_spent_seconds'),
        count=Count('id')
    )
    
    status_counts = ExecutionItem.objects.filter(
        is_deleted=False
    ).values('status').annotate(
        count=Count('id')
    )
    
    top_focus_items = ExecutionItem.objects.filter(
        is_deleted=False,
        time_spent_seconds__gt=0
    ).order_by('-time_spent_seconds')[:7]
    
    chart_data = {
        'domain_labels': [d['domain_category'] or 'Uncategorized' for d in domain_time],
        'domain_minutes': [int((d['seconds'] or 0) / 60) for d in domain_time],
        'domain_counts': [d['count'] for d in domain_time],
        'status_labels': [s['status'] for s in status_counts],
        'status_counts': [s['count'] for s in status_counts],
        'top_labels': [item.title for item in top_focus_items],
        'top_minutes': [int(item.time_spent_seconds / 60) for item in top_focus_items],
    }
    
    return render(request, 'analytics.html', {'chart_data_json': json.dumps(chart_data)})


# Dynamic Chart Drilldown (FR-ANALYTICS-002)
def analytics_drilldown_view(request):
    category = request.GET.get('category')
    chart_type = request.GET.get('chart_type')
    
    items = ExecutionItem.objects.filter(is_deleted=False)
    
    if chart_type == 'domain':
        if category == 'Uncategorized':
            items = items.filter(domain_category=None)
        else:
            items = items.filter(domain_category=category)
    elif chart_type == 'status':
        items = items.filter(status=category)
        
    items = items.order_by('-created_at')[:15]
    
    return render(request, 'partials/analytics_drilldown.html', {'items': items, 'category': category})


# Focus Pins
def toggle_pin_view(request, item_id):
    item = get_object_or_404(ExecutionItem, id=item_id, is_deleted=False)
    item.is_pinned = not item.is_pinned
    item.save()
    
    next_url = request.META.get('HTTP_REFERER', 'dashboard')
    return redirect(next_url)


def academy_view(request):
    academy_domains = DomainCategory.objects.filter(is_academy=True)
    
    academy_containers = WorkspaceContainer.objects.filter(
        domain__in=academy_domains,
        is_archived=False
    ).order_by('container_type', 'title')
    
    academy_tasks = ExecutionItem.objects.filter(
        item_type='LearningTask',
        domain__in=academy_domains,
        is_completed=False,
        is_deleted=False,
        is_archived=False
    ).order_by('due_date', 'created_at')
    
    certifications = Certification.objects.all().order_by('renewal_date')
    
    context = {
        'academy_domains': academy_domains,
        'academy_containers': academy_containers,
        'academy_tasks': academy_tasks,
        'certifications': certifications,
    }
    return render(request, 'academy.html', context)


def certification_add_view(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        achieved = request.POST.get('achieved_date')
        renewal = request.POST.get('renewal_date')
        req = request.POST.get('pdus_required', '0')
        earned = request.POST.get('pdus_earned', '0')
        
        if title:
            Certification.objects.create(
                title=title,
                achieved_date=achieved if achieved else None,
                renewal_date=renewal if renewal else None,
                pdus_required=int(req) if req.isdigit() else 0,
                pdus_earned=int(earned) if earned.isdigit() else 0,
            )
            messages.success(request, f"Certification '{title}' added successfully!")
            
        return redirect('academy')
    return redirect('academy')


def certification_delete_view(request, cert_id):
    cert = get_object_or_404(Certification, id=cert_id)
    title = cert.title
    cert.delete()
    messages.success(request, f"Certification '{title}' deleted.")
    return redirect('academy')


# ==============================================================================
# V4.0 Interactive Planner Dashboard
# ==============================================================================

def planner_view(request):
    """
    Renders the V4 Planner Grid featuring FullCalendar and NL input form.
    """
    settings = AppSettings.get_solo()
    
    from .models import ScheduledTaskAllocation, GoogleCalendarEvent
    allocations = ScheduledTaskAllocation.objects.all()
    cal_events = GoogleCalendarEvent.objects.all()
    
    context = {
        'settings': settings,
        'allocations': allocations,
        'cal_events': cal_events,
    }
    return render(request, 'planner.html', context)


def planner_parse_nl_view(request):
    """
    HTMX endpoint for taking natural language, parsing via SLM, and re-running the solver.
    """
    from django.http import HttpResponse
    
    if request.method == 'POST':
        nl_text = request.POST.get('nl_text', '').strip()
        if not nl_text:
            return HttpResponse('<div class="text-red-500 text-sm">Please enter a task.</div>')
            
        from .slm_parser import parse_natural_language_constraints, SLMParseError
        from .scheduler import generate_schedule_for_date
        import datetime
        from django.utils import timezone
        
        try:
            # 1. Parse via SLM
            constraints = parse_natural_language_constraints(nl_text)
            
            # 2. Extract into ExecutionItem
            from .models import ExecutionItem
            # Provide raw text as title for MVP
            title = nl_text
            if len(title) > 255: title = title[:252] + '...'
            
            new_item = ExecutionItem.objects.create(
                title=title,
                item_type='Task',
                status='Planned',
                duration_estimate=constraints.get('duration_minutes') or 30,
                priority=constraints.get('priority') or 'Medium',
                urgency=constraints.get('urgency') or 'Normal',
            )
            
            # 3. Rerun the solver
            target = timezone.now().date()
            if constraints.get('target_date'):
                try:
                    target = datetime.datetime.strptime(constraints.get('target_date'), "%Y-%m-%d").date()
                except ValueError:
                    pass
                    
            generate_schedule_for_date(target)
            
            return HttpResponse(
                f'<div class="text-green-500 text-sm font-bold bg-green-500/10 p-2 rounded border border-green-500/20 mb-2">Successfully scheduled and updated grid!</div>'
                f'<script>setTimeout(() => window.location.reload(), 1500);</script>'
            )
            
        except SLMParseError as e:
            return HttpResponse(f'<div class="text-red-400 text-sm font-bold bg-red-500/10 p-2 rounded border border-red-500/20">SLM Engine Error: {str(e)}</div>')
        except Exception as e:
            return HttpResponse(f'<div class="text-red-400 text-sm font-bold bg-red-500/10 p-2 rounded border border-red-500/20">System Error: {str(e)}</div>')
            
    return HttpResponse('Invalid method', status=405)


def planner_toggle_blocking_view(request, event_id):
    """
    Toggles the is_blocking flag on a GoogleCalendarEvent and re-runs the solver.
    """
    from .models import GoogleCalendarEvent
    from .scheduler import generate_schedule_for_date
    from django.shortcuts import get_object_or_404, redirect
    
    event = get_object_or_404(GoogleCalendarEvent, id=event_id)
    event.is_blocking = not event.is_blocking
    event.save()
    
    generate_schedule_for_date(event.start_time.date())
    
    return redirect('planner')