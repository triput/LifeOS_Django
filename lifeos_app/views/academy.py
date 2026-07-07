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

