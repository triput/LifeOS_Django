# ==============================================================================
# File: lifeos_app/services/saved_views.py
# Description: Persist and apply facet presets (P4-ENG-VIEWS / ENG-VIEWS)
# Component: Services / Saved Views
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Named SavedView CRUD and URL building for Matrix / Overview / Board."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from django.urls import reverse
from django.utils.text import slugify

from lifeos_app.models import SavedView, SystemEnums

SURFACE_URL: dict[str, str] = {
    SystemEnums.SavedViewSurface.MATRIX: "canvas-matrix",
    SystemEnums.SavedViewSurface.OVERVIEW: "canvas-overview",
    SystemEnums.SavedViewSurface.BOARD: "canvas-board",
}

VALID_SURFACES = frozenset(SURFACE_URL.keys())


@dataclass
class SaveViewResult:
    ok: bool
    message: str = ""
    view: SavedView | None = None


def normalize_params(raw: dict | None) -> dict:
    """Drop empty values; coerce booleans/flags to query-friendly strings."""
    if not raw:
        return {}
    out: dict = {}
    for key, value in raw.items():
        if value is None or value == "" or value is False:
            continue
        if value is True:
            out[str(key)] = "1"
            continue
        out[str(key)] = str(value)
    return out


def params_from_query_string(qs: str) -> dict:
    """Parse `a=1&b=2` into a params dict."""
    from urllib.parse import parse_qs

    qs = (qs or "").lstrip("?")
    if not qs.strip():
        return {}
    parsed = parse_qs(qs, keep_blank_values=False)
    return {k: v[0] for k, v in parsed.items() if v and v[0]}


def facets_to_params(facets) -> dict:
    """Serialize a facets dataclass via its query_string() when available."""
    if hasattr(facets, "query_string"):
        return params_from_query_string(facets.query_string())
    return normalize_params(getattr(facets, "__dict__", {}))


def unique_slug(title: str, *, exclude_pk: int | None = None) -> str:
    """Slugify title with numeric suffix if needed."""
    base = slugify(title) or "view"
    candidate = base
    n = 2
    while True:
        qs = SavedView.objects.filter(slug=candidate)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return candidate
        candidate = f"{base}-{n}"
        n += 1


def save_view(
    *,
    title: str,
    target_surface: str,
    query_params: dict | None = None,
    slug: str = "",
    is_pinned: bool = False,
) -> SaveViewResult:
    """Create or update a SavedView by slug (or title-derived slug)."""
    title = (title or "").strip()[:100]
    if not title:
        return SaveViewResult(ok=False, message="View name required.")
    surface = (target_surface or "").strip().lower()
    if surface not in VALID_SURFACES:
        return SaveViewResult(
            ok=False,
            message=f"Surface must be one of: {', '.join(sorted(VALID_SURFACES))}.",
        )
    params = normalize_params(query_params)
    want_slug = (slug or "").strip() or unique_slug(title)
    existing = SavedView.objects.filter(slug=want_slug).first()
    if existing:
        existing.title = title
        existing.target_surface = surface
        existing.query_params = params
        if is_pinned:
            existing.is_pinned = True
        existing.is_archived = False
        existing.save()
        return SaveViewResult(ok=True, message=f"Updated view “{existing.title}”.", view=existing)

    view = SavedView.objects.create(
        title=title,
        slug=want_slug,
        target_surface=surface,
        query_params=params,
        is_pinned=is_pinned,
    )
    return SaveViewResult(ok=True, message=f"Saved view “{view.title}”.", view=view)


def get_view(slug: str) -> SavedView | None:
    """Lookup active (non-archived) view by slug."""
    return (
        SavedView.objects.filter(slug=(slug or "").strip(), is_archived=False).first()
    )


def list_views(*, surface: str | None = None, pinned_only: bool = False):
    """Ordered queryset of active saved views."""
    qs = SavedView.objects.filter(is_archived=False)
    if surface:
        qs = qs.filter(target_surface=surface)
    if pinned_only:
        qs = qs.filter(is_pinned=True)
    return qs.order_by("-is_pinned", "title")


def build_view_url(view: SavedView) -> str:
    """Absolute path to the target surface with stored query params."""
    url_name = SURFACE_URL.get(view.target_surface)
    if not url_name:
        return reverse("home")
    base = reverse(url_name)
    params = normalize_params(view.query_params or {})
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def views_bar_context(*, surface: str, facets=None, message: str = "", ok: bool | None = None) -> dict:
    """Context fragment for the saved-views chip bar on a surface."""
    current_qs = ""
    if facets is not None and hasattr(facets, "query_string"):
        current_qs = facets.query_string()
    return {
        "saved_views": list(list_views(surface=surface)),
        "pinned_views": list(list_views(pinned_only=True)[:8]),
        "views_surface": surface,
        "views_query_string": current_qs,
        "views_message": message,
        "views_ok": ok,
    }
