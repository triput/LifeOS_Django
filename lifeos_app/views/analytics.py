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

