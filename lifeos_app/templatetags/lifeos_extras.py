# ==============================================================================
# File: lifeos_app/templatetags/lifeos_extras.py
# Description: Template filters for LifeOS V2 presentation helpers
# Component: Templates / Filters
# Version: 1.2 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-11
# ==============================================================================
"""Custom template filters — durations, due pulse, a11y labels (P5-06)."""

from django import template
from django.utils import timezone

from lifeos_app.services.due_pulse import classify_due_urgency, soon_window_minutes
from lifeos_app.services.time_format import format_duration_minutes, format_duration_seconds

register = template.Library()


@register.filter
def duration_h(minutes):
    """Format minutes as human-readable duration for templates."""
    if minutes is None:
        return "—"
    try:
        return format_duration_minutes(int(minutes))
    except (TypeError, ValueError):
        return "—"


@register.filter
def duration_s(seconds):
    """Format seconds as human-readable duration (Analytics / focus totals)."""
    if seconds is None:
        return "—"
    try:
        return format_duration_seconds(int(seconds))
    except (TypeError, ValueError):
        return "—"


@register.simple_tag(takes_context=True)
def due_urgency(context, item):
    """Classify item due urgency once per render (caches window + now on context)."""
    bucket = context.setdefault("_lifeos_due_pulse", {})
    if "soon_minutes" not in bucket:
        bucket["soon_minutes"] = soon_window_minutes()
        bucket["now"] = timezone.now()
    return classify_due_urgency(
        item,
        now=bucket["now"],
        soon_minutes=bucket["soon_minutes"],
    )


@register.simple_tag(takes_context=True)
def due_urgency_label(context, item):
    """Human label for due urgency — screen readers (P5-06)."""
    code = due_urgency(context, item)
    if code == "overdue":
        return "Overdue"
    if code == "soon":
        return "Due soon"
    return ""
