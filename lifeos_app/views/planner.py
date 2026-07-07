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
def planner_view(request):
    """
    Renders the V4 Planner Grid featuring FullCalendar and NL input form.
    """
    from django.urls import reverse
    settings = AppSettings.get_solo()
    
    # Removed synchronous Google Calendar sync from views to resolve latency issues (PERF-06)
        
    from ..models import ScheduledTaskAllocation, GoogleCalendarEvent, ExecutionItem
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
            
        from ..slm_parser import parse_natural_language_constraints, SLMParseError
        from ..scheduler import generate_schedule_for_date
        import datetime
        from django.utils import timezone
        
        try:
            # 1. Parse via SLM
            constraints = parse_natural_language_constraints(nl_text)
            
            # 2. Extract into ExecutionItem
            from ..models import ExecutionItem
            
            title = constraints.get('title')
            if not title:
                title = nl_text
            if len(title) > 255: title = title[:252] + '...'
            
            from ..models import AppSettings
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
    from ..models import GoogleCalendarEvent
    from ..scheduler import generate_schedule_for_date
    from django.shortcuts import get_object_or_404, redirect
    
    event = get_object_or_404(GoogleCalendarEvent, id=event_id)
    event.is_blocking = not event.is_blocking
    event.save()
    
    generate_schedule_for_date(event.start_time.date())
    
    return redirect('planner')

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
    
    import json
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    credentials_dict = None
    
    if google_creds_json:
        try:
            credentials_dict = json.loads(google_creds_json)
        except Exception as e:
            messages.error(request, f"Invalid GOOGLE_CREDENTIALS_JSON environment variable formatting: {str(e)}")
            return redirect('settings')
            
    if not credentials_dict:
        credentials_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'credentials.json')
        if not os.path.exists(credentials_path):
            messages.error(request, "Missing credentials.json file in the project root or GOOGLE_CREDENTIALS_JSON environment variable.")
            return redirect('settings')
            
    try:
        if credentials_dict:
            flow = Flow.from_client_config(
                credentials_dict,
                scopes=['https://www.googleapis.com/auth/calendar.readonly']
            )
        else:
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
    from ..models import CalendarIntegration
    
    # Allow insecure HTTP for local dev OAuth2 flow
    from django.conf import settings
    if settings.DEBUG:
        os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    state = request.session.get('state')
    if not state:
        messages.error(request, "Missing state in session.")
        return redirect('settings')
        
    redirect_uri = request.build_absolute_uri('/settings/calendar/oauth2callback/')
    import json
    google_creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    credentials_dict = None
    
    if google_creds_json:
        try:
            credentials_dict = json.loads(google_creds_json)
        except Exception:
            pass
            
    if not credentials_dict:
        credentials_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'credentials.json')
        if not os.path.exists(credentials_path):
            messages.error(request, "Missing credentials.json file in the project root or GOOGLE_CREDENTIALS_JSON environment variable.")
            return redirect('settings')
            
    try:
        if credentials_dict:
            flow = Flow.from_client_config(
                credentials_dict,
                scopes=['https://www.googleapis.com/auth/calendar.readonly'],
                state=state
            )
        else:
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
        from ..scheduler import sync_google_calendar_events
        try:
            sync_google_calendar_events(force=True)
        except Exception:
            pass
            
        messages.success(request, "Google Calendar linked successfully!")
        
    except Exception as e:
        messages.error(request, f"OAuth error: {str(e)}")
        
    return redirect('settings')

