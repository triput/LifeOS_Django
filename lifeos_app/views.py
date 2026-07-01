# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/views.py
# Description: Views implementing auth, focus engine controls, and context HUD logic
# Component: Core / Views
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-30
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

from .models import WorkspaceContainer, ExecutionItem, AppSettings, DomainCategory, Certification, RecurringConfig, GoogleCalendar, NotionIntegration, parse_duration_to_seconds, format_seconds_to_duration, Tag, CalendarIntegration
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


# Inbox Triage View (FR-INBOX-002)
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


# Settings View & Diagnostics (FR-SETTINGS-001 / FR-SETTINGS-002)
@login_required
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
        
        # V5 Settings
        db_url = request.POST.get('database_url')
        if db_url is not None:
            db_url = db_url.strip()
            if db_url and not db_url.startswith(('postgresql://', 'postgres://', 'sqlite:///')):
                messages.error(request, "Invalid Database URL format. Must start with postgresql:// or sqlite:///")
            else:
                import dotenv
                from django.conf import settings as django_settings
                env_path = django_settings.BASE_DIR / '.env'
                # Only save if it actually changed
                current_env = dotenv.dotenv_values(env_path)
                if current_env.get('DATABASE_URL') != db_url:
                    dotenv.set_key(str(env_path), 'DATABASE_URL', db_url)
                    messages.warning(request, "Database URL changed! You MUST manually restart the Django server for this to take effect.")

        # Phase 5 UI & Scheduler settings
        settings.respect_child_dates_by_default = request.POST.get('respect_child_dates_by_default') == 'on'
        
        buffer_min = request.POST.get('scheduler_buffer_minutes')
        if buffer_min:
            try: settings.scheduler_buffer_minutes = int(buffer_min)
            except ValueError: pass
            
        settings.theme_mode = request.POST.get('theme_mode', settings.theme_mode)
        settings.theme_light_start = request.POST.get('theme_light_start', settings.theme_light_start)
        settings.theme_dark_start = request.POST.get('theme_dark_start', settings.theme_dark_start)

        settings.save()
        messages.success(request, "Settings updated successfully!")
        return redirect('settings')
        
    try:
        import zoneinfo
        available_timezones = sorted(zoneinfo.available_timezones())
    except ImportError:
        import pytz
        available_timezones = pytz.all_timezones
        
    import dotenv
    from django.conf import settings as django_settings
    env_path = django_settings.BASE_DIR / '.env'
    env_vars = dotenv.dotenv_values(env_path)
    current_db_url = env_vars.get('DATABASE_URL', '')

    domains = DomainCategory.objects.all().order_by('name')
    calendars = GoogleCalendar.objects.all().order_by('name')
    tags = Tag.objects.all().order_by('name')
    calendar_integrations = CalendarIntegration.objects.all().order_by('-created_at')
    context = {
        'settings': settings,
        'timezones': available_timezones,
        'current_db_url': current_db_url,
        'domains': domains,
        'calendars': calendars,
        'tags': tags,
        'calendar_integrations': calendar_integrations,
    }
    return render(request, 'settings.html', context)


@login_required
@require_POST
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


@login_required
@require_POST
def domain_delete_view(request, domain_id):
    domain = get_object_or_404(DomainCategory, id=domain_id)
    name = domain.name
    domain.delete()
    messages.success(request, f"Domain '{name}' deleted successfully!")
    return redirect('settings')


@login_required
@require_POST
def calendar_add_view(request):
    if request.method == 'POST':
        cal_id = request.POST.get('calendar_id', '').strip()
        name = request.POST.get('name', 'Primary').strip()
        if cal_id:
            GoogleCalendar.objects.create(calendar_id=cal_id, name=name)
            messages.success(request, f"Google Calendar '{name}' integrated successfully!")
        return redirect('settings')
    return redirect('settings')


@login_required
@require_POST
def calendar_delete_view(request, calendar_id):
    cal = get_object_or_404(GoogleCalendar, id=calendar_id)
    name = cal.name
    cal.delete()
    messages.success(request, f"Calendar '{name}' disconnected.")
    return redirect('settings')


@login_required
@require_POST
def calendar_toggle_active_view(request, cal_id):
    cal = get_object_or_404(GoogleCalendar, id=cal_id)
    cal.is_active = not cal.is_active
    cal.save()
    messages.success(request, f"Calendar '{cal.name}' set to {'Active' if cal.is_active else 'Inactive'}.")
    return redirect('settings')


@login_required
def tags_manager_view(request):
    """
    Renders the dedicated Tag Manager page with domain category scoping.
    """
    tags = Tag.objects.all().select_related('domain').order_by('domain__name', 'name')
    domains = DomainCategory.objects.all().order_by('name')
    context = {
        'tags': tags,
        'domains': domains,
    }
    return render(request, 'tags_manager.html', context)


@login_required
def tag_add_view(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '#9966CC').strip()
        domain_id = request.POST.get('domain_id')
        
        domain = None
        if domain_id:
            domain = get_object_or_404(DomainCategory, id=domain_id)
            
        if name:
            Tag.objects.create(name=name, color=color, domain=domain)
            messages.success(request, f"Tag '{name}' created successfully!")
        else:
            messages.error(request, "Tag name cannot be empty.")
    return redirect('tags-manager')


@login_required
def tag_edit_view(request, tag_id):
    tag = get_object_or_404(Tag, id=tag_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '').strip()
        domain_id = request.POST.get('domain_id')
        
        domain = None
        if domain_id:
            domain = get_object_or_404(DomainCategory, id=domain_id)
            
        if name:
            tag.name = name
            tag.domain = domain
            if color:
                tag.color = color
            tag.save()
            messages.success(request, f"Tag '{name}' updated successfully!")
        else:
            messages.error(request, "Tag name cannot be empty.")
    return redirect('tags-manager')


@login_required
@require_POST
def tag_delete_view(request, tag_id):
    tag = get_object_or_404(Tag, id=tag_id)
    name = tag.name
    if tag.containers.exists() or tag.execution_items.exists():
        messages.error(request, f"Tag '{name}' cannot be deleted because it is still associated with containers or tasks.")
    else:
        tag.delete()
        messages.success(request, f"Tag '{name}' deleted successfully!")
    return redirect('tags-manager')


@login_required
@require_POST
def tag_retag_view(request, tag_id):
    source_tag = get_object_or_404(Tag, id=tag_id)
    target_action = request.POST.get('target_tag_id')
    
    if not target_action:
        messages.error(request, "No action selected.")
        return redirect('tags-manager')
        
    containers = list(source_tag.containers.all())
    items = list(source_tag.execution_items.all())
    
    if target_action == 'clear':
        # Remove source tag from all items
        for c in containers:
            c.tags.remove(source_tag)
        for item in items:
            item.tags.remove(source_tag)
        messages.success(request, f"Cleared tag '{source_tag.name}' from all associated containers and tasks.")
    else:
        target_tag = get_object_or_404(Tag, id=target_action)
        # Shift all items to target tag, then remove source tag
        for c in containers:
            c.tags.add(target_tag)
            c.tags.remove(source_tag)
        for item in items:
            item.tags.add(target_tag)
            item.tags.remove(source_tag)
        messages.success(request, f"Re-tagged all items from '{source_tag.name}' to '{target_tag.name}'.")
        
    return redirect('tags-manager')


@login_required
def backup_view(request):
    if request.method == 'POST':
        try:
            from .models import DomainCategory, Tag, Certification, RecurringConfig, NotionIntegration, GoogleCalendar, CalendarIntegration, TimeAvailabilityBlock, AppSettings
            
            containers = WorkspaceContainer.objects.all()
            items = ExecutionItem.objects.all()
            domains = DomainCategory.objects.all()
            tags = Tag.objects.all()
            certs = Certification.objects.all()
            recurrings = RecurringConfig.objects.all()
            notions = NotionIntegration.objects.all()
            calendars = GoogleCalendar.objects.all()
            integrations = CalendarIntegration.objects.all()
            blocks = TimeAvailabilityBlock.objects.all()
            settings_objs = AppSettings.objects.all()
            
            combined_data = (
                list(settings_objs) + list(domains) + list(tags) + list(certs) +
                list(containers) + list(items) + list(recurrings) + list(notions) +
                list(calendars) + list(integrations) + list(blocks)
            )
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


def parse_datetime_input_tz(val):
    from .context_processors import parse_datetime_input
    return parse_datetime_input(val)


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


# Interactive Analytics Dashboard (FR-ANALYTICS-001)
@login_required
def analytics_view(request):
    domain_time = ExecutionItem.objects.filter(
        is_deleted=False
    ).values('domain__name').annotate(
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
        'domain_labels': [d['domain__name'] or 'Uncategorized' for d in domain_time],
        'domain_minutes': [int((d['seconds'] or 0) / 60) for d in domain_time],
        'domain_counts': [d['count'] for d in domain_time],
        'status_labels': [s['status'] for s in status_counts],
        'status_counts': [s['count'] for s in status_counts],
        'top_labels': [item.title for item in top_focus_items],
        'top_minutes': [int(item.time_spent_seconds / 60) for item in top_focus_items],
    }
    
    return render(request, 'analytics.html', {'chart_data_json': json.dumps(chart_data)})


# Dynamic Chart Drilldown (FR-ANALYTICS-002)
@login_required
def analytics_drilldown_view(request):
    category = request.GET.get('category')
    chart_type = request.GET.get('chart_type')
    
    items = ExecutionItem.objects.filter(is_deleted=False)
    
    if chart_type == 'domain':
        if category == 'Uncategorized':
            items = items.filter(domain__isnull=True)
        else:
            items = items.filter(domain__name=category)
    elif chart_type == 'status':
        items = items.filter(status=category)
        
    items = items.order_by('-created_at')[:15]
    
    return render(request, 'partials/analytics_drilldown.html', {'items': items, 'category': category})


# Focus Pins
@login_required
@require_POST
def toggle_pin_view(request, item_id):
    item = get_object_or_404(ExecutionItem, id=item_id, is_deleted=False)
    item.is_pinned = not item.is_pinned
    item.save()
    
    next_url = request.META.get('HTTP_REFERER', 'dashboard')
    return redirect(next_url)


@login_required
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
    
    certifications = Certification.objects.annotate(
        total_container_credits=Sum('containers__credits_earned')
    ).order_by('renewal_date')
    
    for cert in certifications:
        total_credits = cert.total_container_credits or 0
        cert.total_earned = cert.pdus_earned + total_credits
        if cert.pdus_required > 0:
            cert.progress_percent = min(100, int((cert.total_earned / float(cert.pdus_required)) * 100))
        else:
            cert.progress_percent = 100
            
    context = {
        'academy_domains': academy_domains,
        'academy_containers': academy_containers,
        'academy_tasks': academy_tasks,
        'certifications': certifications,
    }
    return render(request, 'academy.html', context)


@login_required
@require_POST
def certification_add_view(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        provider = request.POST.get('provider', '').strip()
        description = request.POST.get('description', '').strip()
        credit_unit_type = request.POST.get('credit_unit_type', 'Hours').strip()
        achieved = request.POST.get('achieved_date')
        renewal = request.POST.get('renewal_date')
        req = request.POST.get('pdus_required', '0')
        earned = request.POST.get('pdus_earned', '0')
        
        if title:
            Certification.objects.create(
                title=title,
                provider=provider,
                description=description,
                credit_unit_type=credit_unit_type,
                achieved_date=achieved if achieved else None,
                renewal_date=renewal if renewal else None,
                pdus_required=int(req) if req.isdigit() else 0,
                pdus_earned=int(earned) if earned.isdigit() else 0,
            )
            messages.success(request, f"Certification '{title}' added successfully!")
            
        return redirect('academy')
    return redirect('academy')


@login_required
@require_POST
def certification_delete_view(request, cert_id):
    cert = get_object_or_404(Certification, id=cert_id)
    title = cert.title
    cert.delete()
    messages.success(request, f"Certification '{title}' deleted.")
    return redirect('academy')


# ==============================================================================
# V4.0 Interactive Planner Dashboard
# ==============================================================================

@login_required
def planner_view(request):
    """
    Renders the V4 Planner Grid featuring FullCalendar and NL input form.
    """
    from django.urls import reverse
    settings = AppSettings.get_solo()
    
    # Removed synchronous Google Calendar sync from views to resolve latency issues (PERF-06)
        
    from .models import ScheduledTaskAllocation, GoogleCalendarEvent, ExecutionItem
    allocations = ScheduledTaskAllocation.objects.select_related(
        'execution_item__domain'
    ).prefetch_related(
        'execution_item__tags'
    ).all()
    cal_events = GoogleCalendarEvent.objects.all()
    
    # Fetch timezone-aware midnight items that are unallocated
    try:
        import zoneinfo
        user_tz = zoneinfo.ZoneInfo(settings.timezone)
    except Exception:
        try:
            import pytz
            user_tz = pytz.timezone(settings.timezone)
        except Exception:
            from django.utils import timezone
            user_tz = timezone.get_current_timezone()

    import datetime
    from django.db.models import Exists, OuterRef
    alloc_sub = ScheduledTaskAllocation.objects.filter(execution_item=OuterRef('pk'))
    all_uncompleted = ExecutionItem.objects.filter(
        is_completed=False,
        is_deleted=False,
        start_date__isnull=False
    ).annotate(has_alloc=Exists(alloc_sub)).filter(has_alloc=False).select_related('domain')
    
    unallocated_items = []
    for item in all_uncompleted:
        local_start = item.start_date.astimezone(user_tz)
        if local_start.hour == 0 and local_start.minute == 0:
            unallocated_items.append(item)
                
    import json
    # Serialize unallocated grooming items
    unallocated_serialized = []
    for item in unallocated_items:
        local_start = item.start_date.astimezone(user_tz)
        unallocated_serialized.append({
            'title': f"⚠️ [Groom] {item.title}",
            'start': local_start.date().isoformat(),
            'allDay': True,
            'backgroundColor': '#d9770622',
            'borderColor': '#d97706',
            'textColor': '#fbbf24',
            'extendedProps': {
                'type': 'unallocated'
            }
        })
        
    # Serialize Google Calendar events
    cal_events_serialized = []
    for ev in cal_events:
        local_start = ev.start_time.astimezone(user_tz)
        local_end = ev.end_time.astimezone(user_tz)
        is_all_day = (local_start.hour == 0 and local_start.minute == 0 and
                      local_end.hour == 0 and local_end.minute == 0)
        
        cal_events_serialized.append({
            'id': f"cal_{ev.id}",
            'title': ev.title,
            'start': local_start.date().isoformat() if is_all_day else local_start.isoformat(),
            'end': local_end.date().isoformat() if is_all_day else local_end.isoformat(),
            'allDay': is_all_day,
            'backgroundColor': '#E0115F22' if ev.is_blocking else '#1f293766',
            'borderColor': '#E0115F' if ev.is_blocking else '#374151',
            'textColor': '#fca5a5' if ev.is_blocking else '#9ca3af',
            'url': reverse('planner-toggle-blocking', kwargs={'event_id': ev.id}),
            'extendedProps': {
                'type': 'calendar',
                'is_blocking': str(ev.is_blocking).lower()
            }
        })

    context = {
        'settings': settings,
        'allocations': allocations,
        'unallocated_events_json': json.dumps(unallocated_serialized),
        'cal_events_json': json.dumps(cal_events_serialized),
    }
    return render(request, 'planner.html', context)


@login_required
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
            
            title = constraints.get('title')
            if not title:
                title = nl_text
            if len(title) > 255: title = title[:252] + '...'
            
            from .models import AppSettings
            settings = AppSettings.get_solo()
            try:
                import zoneinfo
                user_tz = zoneinfo.ZoneInfo(settings.timezone)
            except Exception:
                try:
                    import pytz
                    user_tz = pytz.timezone(settings.timezone)
                except Exception:
                    user_tz = timezone.get_current_timezone()

            target = timezone.now().astimezone(user_tz).date()
            if constraints.get('target_date'):
                try:
                    target = datetime.datetime.strptime(constraints.get('target_date'), "%Y-%m-%d").date()
                except ValueError:
                    pass

            duration = constraints.get('duration_minutes') or 30
            start_dt = None
            end_dt = None

            if constraints.get('target_time'):
                try:
                    t_time = datetime.datetime.strptime(constraints.get('target_time'), "%H:%M").time()
                    dt = datetime.datetime.combine(target, t_time)
                    start_dt = timezone.make_aware(dt, user_tz)
                    end_dt = start_dt + datetime.timedelta(minutes=duration)
                except Exception:
                    pass
            
            new_item = ExecutionItem.objects.create(
                title=title,
                item_type='Task',
                status='Planned',
                duration_estimate=duration,
                priority=constraints.get('priority') or 'Medium',
                urgency=constraints.get('urgency') or 'Normal',
                start_date=start_dt,
                end_date=end_dt,
            )
            
            # 3. Rerun the solver
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


# ==============================================================================
# V5.1 Hierarchical Backlog Grid Editor views
# ==============================================================================

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
    value = request.POST.get('value', '').strip()
    
    if not model_type or not model_id or not field:
        return HttpResponse("Missing fields", status=400)
        
    if model_type == 'container':
        obj = get_object_or_404(WorkspaceContainer, id=model_id)
    elif model_type == 'item':
        obj = get_object_or_404(ExecutionItem, id=model_id)
    else:
        return HttpResponse("Invalid model type", status=400)
        
    try:
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
            tag_ids = request.POST.getlist('value')
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
            
        from .scheduler import generate_schedule_for_date
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
            
        from .scheduler import generate_schedule_for_date
        for d in dates_to_reschedule:
            generate_schedule_for_date(d)
            
        messages.success(request, f"Bulk updated fuzzy timeframe to '{fuzzy_val}' on {updated_tasks} tasks.")

    response = HttpResponse()
    response['HX-Refresh'] = 'true'
    return response


# ==============================================================================
# V5 Kanban Views
# ==============================================================================

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


# ==============================================================================
# Roadmap & Agenda Views
# ==============================================================================

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
    from .models import ScheduledTaskAllocation
    
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


# ==============================================================================
# Google Calendar Integration Views (Phase 4)
# ==============================================================================

@login_required
def calendar_auth_view(request):
    """
    Initiate the Google OAuth2 flow.
    """
    import os
    from google_auth_oauthlib.flow import Flow
    
    # Allow insecure HTTP for local dev OAuth2 flow
    from django.conf import settings
    if settings.DEBUG:
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    # Needs to match the Authorized redirect URI in Google Cloud Console
    redirect_uri = request.build_absolute_uri('/settings/calendar/oauth2callback/')
    
    credentials_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'credentials.json')
    
    if not os.path.exists(credentials_path):
        messages.error(request, "Missing credentials.json file in the project root.")
        return redirect('settings')
        
    try:
        flow = Flow.from_client_secrets_file(
            credentials_path,
            scopes=['https://www.googleapis.com/auth/calendar.readonly']
        )
        flow.redirect_uri = redirect_uri
        
        # Ensure offline access to get a refresh token
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        
        # Save state and code verifier in session to verify in the callback
        request.session['state'] = state
        if hasattr(flow, 'code_verifier'):
            request.session['code_verifier'] = flow.code_verifier
            
        return redirect(authorization_url)
        
    except Exception as e:
        messages.error(request, f"Failed to initialize OAuth flow: {str(e)}")
        return redirect('settings')


@login_required
def calendar_oauth2callback_view(request):
    """
    Handle the OAuth2 callback from Google.
    """
    import os
    from google_auth_oauthlib.flow import Flow
    from .models import CalendarIntegration
    
    # Allow insecure HTTP for local dev OAuth2 flow
    from django.conf import settings
    if settings.DEBUG:
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    state = request.session.get('state')
    if not state:
        messages.error(request, "Missing state in session.")
        return redirect('settings')
        
    redirect_uri = request.build_absolute_uri('/settings/calendar/oauth2callback/')
    credentials_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'credentials.json')
    
    try:
        flow = Flow.from_client_secrets_file(
            credentials_path,
            scopes=['https://www.googleapis.com/auth/calendar.readonly'],
            state=state
        )
        flow.redirect_uri = redirect_uri
        
        # Restore PKCE code verifier
        code_verifier = request.session.get('code_verifier')
        if code_verifier:
            flow.code_verifier = code_verifier
            
        # Fetch the token using the authorization response (the full URL that Google redirected to)
        authorization_response = request.build_absolute_uri()
        flow.fetch_token(authorization_response=authorization_response)
        
        credentials = flow.credentials
        
        # Try to fetch user info to get email (optional, requires userinfo profile scope, but we can just save it)
        # For now, we just save the credentials to a new CalendarIntegration object
        CalendarIntegration.objects.create(
            user_email="User (OAuth)", 
            credentials_json={
                'token': credentials.token,
                'refresh_token': credentials.refresh_token,
                'token_uri': credentials.token_uri,
                'client_id': credentials.client_id,
                'client_secret': credentials.client_secret,
                'scopes': credentials.scopes
            }
        )
        
        # Force an initial sync to fetch all available calendars immediately
        from .scheduler import sync_google_calendar_events
        try:
            sync_google_calendar_events(force=True)
        except Exception:
            pass
            
        messages.success(request, "Google Calendar linked successfully!")
        
    except Exception as e:
        messages.error(request, f"OAuth error: {str(e)}")
        
    return redirect('settings')


# ==============================================================================
# Phase 5: Container Bounds Warning Verification API
# ==============================================================================

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


@login_required
def user_management_view(request):
    """
    Renders the User Management dashboard (Settings > Users) (FR-SEC-003).
    Only accessible to superusers.
    """
    if not request.user.is_superuser:
        return HttpResponseForbidden("Forbidden: Only the system owner has access to User Management.")
    
    from django.contrib.auth.models import User
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'user_management.html', {'users_list': users})


@login_required
@require_POST
def delete_user_view(request, user_id):
    """
    Handles user account deletions (FR-SEC-003).
    Only accessible to superusers. Prevents self-deletion.
    """
    if not request.user.is_superuser:
        return HttpResponseForbidden("Forbidden: Only the system owner can delete users.")
    
    from django.contrib.auth.models import User
    user_to_delete = get_object_or_404(User, id=user_id)
    
    # Self-deletion prevention
    if user_to_delete == request.user:
        messages.error(request, "Error: You cannot delete your own logged-in account.")
        return redirect('user-management')
        
    username = user_to_delete.username
    user_to_delete.delete()
    messages.success(request, f"User '{username}' was successfully deleted.")
    return redirect('user-management')