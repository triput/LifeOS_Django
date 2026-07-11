# ==============================================================================
# File: lifeos_django/urls.py
# Description: Root URL routing for LifeOS V2 (auth + admin + app)
# Component: Core / URL Configuration
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Root URL configuration for the LifeOS Django project."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from lifeos_app import views as app_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", app_views.login_view, name="login"),
    path("setup/", app_views.setup_owner_view, name="setup-owner"),
    path("logout/", app_views.logout_view, name="logout"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html"
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset-confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset-complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("", include("lifeos_app.urls")),
]
