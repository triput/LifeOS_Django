# ==============================================================================
# File: f:/Code Repo/LifeOS_Django/lifeos_django/urls.py
# Description: Root URL routing configurations mapping core views and admin modules
# Component: Core / URL Configuration
# Version: 1.0 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-06-30
# ==============================================================================
"""Root URL configuration for lifeos_django project."""

from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from lifeos_app import views as app_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", app_views.login_view, name="login"),
    path("logout/", app_views.logout_view, name="logout"),
    
    # Password Reset Endpoints
    path("password-reset/", auth_views.PasswordResetView.as_view(template_name='registration/password_reset_form.html'), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'), name="password_reset_done"),
    path("password-reset-confirm/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'), name="password_reset_confirm"),
    path("password-reset-complete/", auth_views.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'), name="password_reset_complete"),
    
    # Password Change Endpoints (Logged-In)
    path("password-change/", auth_views.PasswordChangeView.as_view(template_name='registration/password_change_form.html'), name="password_change"),
    path("password-change/done/", auth_views.PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name="password_change_done"),
    
    path("", include("lifeos_app.urls")),
]

