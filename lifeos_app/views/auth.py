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

