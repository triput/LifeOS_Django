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
            from ..models import DomainCategory, Tag, Certification, RecurringConfig, NotionIntegration, GoogleCalendar, CalendarIntegration, TimeAvailabilityBlock, AppSettings
            
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
            
            backup_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'backup')
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

