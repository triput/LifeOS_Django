# ==============================================================================
# File: lifeos_app/views/auth.py
# Description: Login / logout views for the single-owner cockpit
# Component: Core / Auth Views
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Authentication entry points for LifeOS V2."""

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from lifeos_app.services.owner import create_owner_user, owner_exists


def login_view(request):
    """Render login form and authenticate the owner superuser."""
    if not owner_exists():
        return redirect("setup-owner")

    if request.user.is_authenticated and request.user.is_superuser:
        return redirect("home")

    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_superuser:
            login(request, user)
            return redirect(request.GET.get("next") or "home")
        error = "Invalid credentials or non-owner account."

    return render(request, "registration/login.html", {"error": error, "needs_setup": False})


def setup_owner_view(request):
    """First-run owner provisioning — only available before any superuser exists."""
    if owner_exists():
        if request.user.is_authenticated and request.user.is_superuser:
            return redirect("home")
        return redirect("login")

    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        password_confirm = request.POST.get("password_confirm", "")
        email = request.POST.get("email", "").strip()

        if password != password_confirm:
            error = "Passwords do not match."
        else:
            try:
                user, _ = create_owner_user(username, password, email)
                login(request, user)
                return redirect("home")
            except ValidationError as exc:
                error = exc.messages[0] if exc.messages else str(exc)

    return render(request, "registration/setup_owner.html", {"error": error})


@login_required
def logout_view(request):
    """End the owner session and return to login."""
    logout(request)
    return redirect("login")
