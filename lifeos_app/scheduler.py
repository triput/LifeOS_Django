# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_app/scheduler.py
# Description: Deterministic Greedy Interval Solver for V4 Alternate SLM Engine
# Component: Core / Scheduling Engine
# Version: 1.0 (Gold Master)
# Created: 2026-06-27
# Last Update: 2026-06-27
# ==============================================================================

import datetime
from django.utils import timezone
from .models import (
    ExecutionItem, AppSettings, GoogleCalendarEvent, 
    TimeAvailabilityBlock, ScheduledTaskAllocation
)

def _get_weight(value):
    mapping = {
        'Low': 1,
        'Medium': 2,
        'Normal': 2,
        'High': 3,
        'Critical': 4,
        'Immediate': 4
    }
    return mapping.get(value, 2)

def calculate_rank_score(item: ExecutionItem, settings: AppSettings) -> float:
    """
    Calculates the heuristic rank score based on user-defined weights.
    Rank Score = (W_priority * priority_weight) + (W_urgency * urgency_weight) - (Duration Minutes * 0.05)
    """
    w_priority = _get_weight(item.priority)
    w_urgency = _get_weight(item.urgency)
    
    score = (w_priority * settings.priority_weight) + (w_urgency * settings.urgency_weight)
    score -= (item.duration_estimate * 0.05)
    
    return max(score, 0.0)

def sync_google_calendar_events(force=False):
    """
    Fetches events from all active Google Calendar integrations and writes to GoogleCalendarEvent.
    Throttled by a cache check of 5 minutes unless force=True.
    """
    from django.core.cache import cache
    if not force and cache.get('gcal_sync_throttle'):
        return
        
    from .models import CalendarIntegration, GoogleCalendar, GoogleCalendarEvent
    
    integrations = CalendarIntegration.objects.filter(sync_enabled=True)
    if not integrations.exists():
        return
        
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from google.auth.transport.requests import Request
    except ImportError:
        return

    for integration in integrations:
        try:
            creds_data = integration.get_credentials()
            if not creds_data:
                continue
                
            creds = Credentials(
                token=creds_data.get('token'),
                refresh_token=creds_data.get('refresh_token'),
                token_uri=creds_data.get('token_uri'),
                client_id=creds_data.get('client_id'),
                client_secret=creds_data.get('client_secret'),
                scopes=creds_data.get('scopes')
            )
            
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                creds_data['token'] = creds.token
                integration.credentials_json = creds_data
                integration.save(update_fields=['credentials_json'])
                
            service = build('calendar', 'v3', credentials=creds)
            
            # Retrieve user's calendars
            calendar_list = service.calendarList().list().execute()
            for cal_entry in calendar_list.get('items', []):
                cal_id = cal_entry['id']
                cal_name = cal_entry.get('summary', 'Google Calendar')
                
                db_cal, _ = GoogleCalendar.objects.get_or_create(
                    calendar_id=cal_id,
                    defaults={'name': cal_name, 'is_active': True}
                )
                
                if not db_cal.is_active:
                    continue
                    
                # Sync events for the next 30 days
                now = datetime.datetime.utcnow().isoformat() + 'Z'
                time_max = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat() + 'Z'
                
                events_result = service.events().list(
                    calendarId=cal_id,
                    timeMin=now,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                
                events = events_result.get('items', [])
                
                # Delete existing events for this calendar to refresh
                GoogleCalendarEvent.objects.filter(calendar=db_cal).delete()
                
                for event in events:
                    is_all_day = 'date' in event['start']
                    
                    from django.utils.dateparse import parse_datetime
                    from django.utils.timezone import is_naive, make_aware
                    
                    if is_all_day:
                        import datetime as dt
                        d_start = dt.date.fromisoformat(event['start']['date'])
                        d_end = dt.date.fromisoformat(event['end']['date'])
                        
                        start_dt = timezone.make_aware(dt.datetime.combine(d_start, dt.time.min))
                        end_dt = timezone.make_aware(dt.datetime.combine(d_end, dt.time.min))
                    else:
                        start_str = event['start'].get('dateTime')
                        end_str = event['end'].get('dateTime')
                        
                        start_dt = parse_datetime(start_str)
                        if is_naive(start_dt): 
                            start_dt = make_aware(start_dt)
                            
                        end_dt = parse_datetime(end_str)
                        if is_naive(end_dt): 
                            end_dt = make_aware(end_dt)
                        
                    GoogleCalendarEvent.objects.get_or_create(
                        calendar=db_cal,
                        event_id=event['id'],
                        defaults={
                            'title': event.get('summary', 'No Title'),
                            'start_time': start_dt,
                            'end_time': end_dt,
                            'is_blocking': True
                        }
                    )
        except Exception as e:
            import logging
            logging.error(f"Error syncing Google Calendar: {str(e)}")
            
    cache.set('gcal_sync_throttle', True, 300)


def generate_schedule_for_date(target_date: datetime.date):
    """
    Wipes existing automated allocations for the target date,
    calculates available free time intervals, and maps prioritized tasks greedily.
    """
    settings = AppSettings.get_solo()
    if not settings.enable_ai_scheduling:
        return
        
    try:
        sync_google_calendar_events()
    except Exception:
        pass
        
    day_name = target_date.strftime("%A").lower()
    
    try:
        import zoneinfo
        user_tz = zoneinfo.ZoneInfo(settings.timezone)
    except Exception:
        try:
            import pytz
            user_tz = pytz.timezone(settings.timezone)
        except Exception:
            user_tz = timezone.get_current_timezone()
    
    # 1. Fetch available blocks for this day
    filter_kwargs = {f'day_{day_name}': True, 'is_active': True}
    blocks = TimeAvailabilityBlock.objects.filter(**filter_kwargs)
    
    if not blocks.exists():
        # Fallback to a default 9-to-5 block if nothing is configured
        fallback_start = datetime.datetime.combine(target_date, settings.start_of_work_day)
        fallback_start = timezone.make_aware(fallback_start, user_tz)
        fallback_end = fallback_start + datetime.timedelta(hours=8)
        free_intervals = [{'start': fallback_start, 'end': fallback_end}]
    else:
        free_intervals = []
        for b in blocks:
            start_dt = timezone.make_aware(datetime.datetime.combine(target_date, b.start_time), user_tz)
            end_dt = timezone.make_aware(datetime.datetime.combine(target_date, b.end_time), user_tz)
            if start_dt < end_dt:
                free_intervals.append({'start': start_dt, 'end': end_dt})
                
    # 2. Subtract blocking Google Calendar events
    day_start = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time.min), user_tz)
    day_end = timezone.make_aware(datetime.datetime.combine(target_date, datetime.time.max), user_tz)
    
    blocking_events = GoogleCalendarEvent.objects.filter(
        start_time__lt=day_end,
        end_time__gt=day_start,
        is_blocking=True
    ).order_by('start_time')
    
    for event in blocking_events:
        new_intervals = []
        for interval in free_intervals:
            # Overlap check
            if event.end_time <= interval['start'] or event.start_time >= interval['end']:
                new_intervals.append(interval) # No overlap
            else:
                # Split the interval
                if interval['start'] < event.start_time:
                    new_intervals.append({'start': interval['start'], 'end': event.start_time})
                if event.end_time < interval['end']:
                    new_intervals.append({'start': event.end_time, 'end': interval['end']})
        free_intervals = new_intervals
        
    # We only clear allocations that are strictly in the future to not ruin past history
    ScheduledTaskAllocation.objects.filter(
        start_time__gte=timezone.now(),
        start_time__date=target_date
    ).delete()

    # Subtract planned tasks that have explicit start/end times set on this date
    fixed_items = ExecutionItem.objects.filter(
        status='Planned',
        is_completed=False,
        is_deleted=False,
        start_date__date=target_date,
        start_date__isnull=False,
        end_date__isnull=False
    )
    
    for item in fixed_items:
        # Pre-allocate in database
        ScheduledTaskAllocation.objects.update_or_create(
            execution_item=item,
            defaults={
                'start_time': item.start_date,
                'end_time': item.end_date,
                'score_metric': 999.0 # Max metric for fixed items
            }
        )
        # Subtract from free intervals
        new_intervals = []
        for interval in free_intervals:
            if item.end_date <= interval['start'] or item.start_date >= interval['end']:
                new_intervals.append(interval)
            else:
                if interval['start'] < item.start_date:
                    new_intervals.append({'start': interval['start'], 'end': item.start_date})
                if item.end_date < interval['end']:
                    new_intervals.append({'start': item.end_date, 'end': interval['end']})
        free_intervals = new_intervals

    # Sort free intervals chronologically
    free_intervals.sort(key=lambda x: x['start'])
    
    # 3. Fetch and rank tasks (excluding fixed items which are pre-allocated)
    candidates = ExecutionItem.objects.filter(
        status='Planned', 
        is_completed=False, 
        is_deleted=False
    ).exclude(id__in=[fi.id for fi in fixed_items])
    
    ranked_items = []
    # Filter out items that already have a future allocation on a different date to avoid rescheduling indefinitely
    for item in candidates:
        if hasattr(item, 'scheduled_allocation') and item.scheduled_allocation.start_time >= timezone.now():
            continue 
        score = calculate_rank_score(item, settings)
        ranked_items.append({'item': item, 'score': score})
        
    ranked_items.sort(key=lambda x: x['score'], reverse=True)
    
    # 4. Greedy Interval Fitting
    for rank_data in ranked_items:
        task = rank_data['item']
        duration_td = datetime.timedelta(minutes=task.duration_estimate)
        
        # Find first fitting interval
        for i, interval in enumerate(free_intervals):
            interval_dur = interval['end'] - interval['start']
            if interval_dur >= duration_td:
                # We have a fit!
                alloc_start = interval['start']
                alloc_end = alloc_start + duration_td
                
                ScheduledTaskAllocation.objects.update_or_create(
                    execution_item=task,
                    defaults={
                        'start_time': alloc_start,
                        'end_time': alloc_end,
                        'score_metric': rank_data['score']
                    }
                )
                
                # Shrink the available interval by task duration + user configured buffer minutes
                buffer_td = datetime.timedelta(minutes=settings.scheduler_buffer_minutes)
                new_start = alloc_end + buffer_td
                if new_start < interval['end']:
                    interval['start'] = new_start
                else:
                    # Interval is fully consumed, remove it
                    interval['start'] = interval['end']
                break # Move to next task
