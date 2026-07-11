# ==============================================================================
# File: lifeos_app/views/academy.py
# Description: Academy Hub surface (P4-SURF-ACADEMY)
# Component: Surfaces / Academy
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Certifications, credits, and course tree progress."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from lifeos_app.services.academy import build_academy_page


@login_required
def academy_view(request):
    """Render Academy Hub — cert meters + recursive course progress."""
    return render(request, "surfaces/academy.html", build_academy_page())
