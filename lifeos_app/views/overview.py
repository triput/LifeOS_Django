# ==============================================================================
# File: lifeos_app/views/overview.py
# Description: Horizon Overview surface (P4-SURF-OVERVIEW)
# Component: Surfaces / Overview
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Cross-container active-leaf aggregator — not the Home Horizon Feed."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from lifeos_app.services.overview import OverviewFacets, build_overview_page


@login_required
def overview_view(request):
    """Render Horizon Overview with facets, group-by, and pagination."""
    from lifeos_app.services.saved_views import views_bar_context

    facets = OverviewFacets.from_request(request)
    ctx = build_overview_page(facets)
    ctx.update(views_bar_context(surface="overview", facets=facets))
    return render(request, "surfaces/overview.html", ctx)
