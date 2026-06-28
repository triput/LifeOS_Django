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

def generate_schedule_for_date(target_date: datetime.date):
    """
    Wipes existing automated allocations for the target date,
    calculates available free time intervals, and maps prioritized tasks greedily.
    """
    settings = AppSettings.get_solo()
    if not settings.enable_ai_scheduling:
        return
        
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
        
    # Sort free intervals chronologically
    free_intervals.sort(key=lambda x: x['start'])
    
    # 3. Fetch and rank tasks
    candidates = ExecutionItem.objects.filter(
        status='Planned', 
        is_completed=False, 
        is_deleted=False
    )
    
    # We only clear allocations that are strictly in the future to not ruin past history
    ScheduledTaskAllocation.objects.filter(
        start_time__gte=timezone.now(),
        start_time__date=target_date
    ).delete()
    
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
                
                # Shrink the available interval
                interval['start'] = alloc_end
                break # Move to next task
