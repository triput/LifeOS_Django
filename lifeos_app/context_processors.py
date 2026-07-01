# ==============================================================================
# File: lifeos_app/context_processors.py
# Description: Custom context processors providing global template objects
# Component: Core / Context Processor
# Version: 1.0 (Gold Master)
# Created: 2026-06-29
# Last Update: 2026-06-29
# ==============================================================================

from .models import AppSettings

def global_settings(request):
    try:
        settings_obj = AppSettings.get_solo()
    except Exception:
        settings_obj = None
    return {
        'app_settings': settings_obj
    }


def get_user_timezone():
    """
    Resolves and returns the ZoneInfo/pytz timezone configured in AppSettings.
    Falls back to system default timezone on failure.
    """
    try:
        settings = AppSettings.get_solo()
        tz_name = settings.timezone
    except Exception:
        tz_name = 'UTC'
        
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(tz_name)
    except Exception:
        try:
            import pytz
            return pytz.timezone(tz_name)
        except Exception:
            from django.utils import timezone
            return timezone.get_current_timezone()


def parse_datetime_input(dt_str):
    """
    Parses ISO datetime input strings (e.g. YYYY-MM-DDTHH:MM) into a tz-aware datetime
    using the active user timezone. Returns None if invalid or empty.
    """
    if not dt_str:
        return None
        
    import datetime
    from django.utils import timezone
    dt_str = str(dt_str).strip()
    try:
        # Match standard HTML5 date-time inputs: "YYYY-MM-DDTHH:MM" or "YYYY-MM-DD HH:MM"
        if 't' in dt_str.lower():
            dt = datetime.datetime.fromisoformat(dt_str)
        else:
            # Fallback for "YYYY-MM-DD HH:MM:SS" or "YYYY-MM-DD HH:MM"
            parts = dt_str.split(' ')
            if len(parts) == 2:
                d_part = datetime.date.fromisoformat(parts[0])
                t_part = datetime.time.fromisoformat(parts[1][:5])
                dt = datetime.datetime.combine(d_part, t_part)
            else:
                d_part = datetime.date.fromisoformat(dt_str)
                dt = datetime.datetime.combine(d_part, datetime.time.min)
                
        user_tz = get_user_timezone()
        return timezone.make_aware(dt, user_tz)
    except Exception:
        return None
