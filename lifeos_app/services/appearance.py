# ==============================================================================
# File: lifeos_app/services/appearance.py
# Description: Appearance settings — themes and domain/tag colors (BL-UI-002/003)
# Component: Services / Appearance
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Persist theme mode and taxonomy colors from Settings."""

from __future__ import annotations

import re

from lifeos_app.models import AppSettings, DomainCategory, Tag
from lifeos_app.services.appearance_defaults import (
    default_domain_color,
    default_tag_color,
)
from lifeos_app.services.settings_surface import SaveResult
from lifeos_app.services.themes import THEME_CHOICES, THEME_HYBRID_DARK, is_valid_theme, resolve_theme_slug

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def normalize_hex_color(value: str, *, fallback: str) -> str:
    """Validate #RRGGBB hex; return fallback when invalid."""
    cleaned = (value or "").strip()
    if _HEX_COLOR.match(cleaned):
        return cleaned.upper()
    return fallback


def save_appearance_settings(
    *,
    theme_mode: str,
    domain_colors: dict[int, str],
    tag_colors: dict[int, str],
) -> SaveResult:
    """Persist theme selection and domain/tag color overrides."""
    solo = AppSettings.get_solo()
    slug = resolve_theme_slug(theme_mode)
    solo.theme_mode = slug if is_valid_theme(slug) else THEME_HYBRID_DARK
    solo.save(update_fields=["theme_mode", "updated_at"])

    updated_domains = 0
    for domain in DomainCategory.objects.filter(is_active=True):
        if domain.pk not in domain_colors:
            continue
        new_color = normalize_hex_color(domain_colors[domain.pk], fallback=domain.color)
        if new_color != domain.color:
            domain.color = new_color
            domain.save(update_fields=["color"])
            updated_domains += 1

    updated_tags = 0
    for tag in Tag.objects.all():
        if tag.pk not in tag_colors:
            continue
        new_color = normalize_hex_color(tag_colors[tag.pk], fallback=tag.color)
        if new_color != tag.color:
            tag.color = new_color
            tag.save(update_fields=["color"])
            updated_tags += 1

    return SaveResult(
        ok=True,
        message=f"Appearance saved — {dict(THEME_CHOICES).get(solo.theme_mode, solo.theme_mode)}; "
        f"{updated_domains} domain(s), {updated_tags} tag(s) updated.",
    )


def reset_domain_colors(*, domain_id: int | None = None) -> SaveResult:
    """Reset one or all active domains to catalog defaults."""
    qs = DomainCategory.objects.filter(is_active=True)
    if domain_id is not None:
        qs = qs.filter(pk=domain_id)
        if not qs.exists():
            return SaveResult(ok=False, message="Domain not found.")
    updated = 0
    for domain in qs:
        target = default_domain_color(domain)
        if domain.color != target:
            domain.color = target
            domain.save(update_fields=["color"])
            updated += 1
    if domain_id is not None:
        domain = qs.first()
        name = domain.name if domain else ""
        return SaveResult(ok=True, message=f"Reset “{name}” to default color.")
    return SaveResult(ok=True, message=f"Reset {updated} domain color(s) to defaults.")


def reset_tag_colors(*, tag_id: int | None = None) -> SaveResult:
    """Reset one or all tags to catalog defaults."""
    qs = Tag.objects.all()
    if tag_id is not None:
        qs = qs.filter(pk=tag_id)
        if not qs.exists():
            return SaveResult(ok=False, message="Tag not found.")
    updated = 0
    for tag in qs:
        target = default_tag_color(tag)
        if tag.color != target:
            tag.color = target
            tag.save(update_fields=["color"])
            updated += 1
    if tag_id is not None:
        tag = qs.first()
        name = tag.name if tag else ""
        return SaveResult(ok=True, message=f"Reset “{name}” to default color.")
    return SaveResult(ok=True, message=f"Reset {updated} tag color(s) to defaults.")


def appearance_context() -> dict:
    """Extra Settings context for the Appearance section."""
    from lifeos_app.services.themes import THEME_CHOICES

    solo = AppSettings.get_solo()
    domains = list(DomainCategory.objects.filter(is_active=True).order_by("name"))
    tags = list(Tag.objects.select_related("domain").order_by("name"))
    return {
        "theme_choices": THEME_CHOICES,
        "theme_slug": resolve_theme_slug(solo.theme_mode),
        "domains": domains,
        "tags": tags,
        "domain_rows": [
            {"domain": d, "default_color": default_domain_color(d)} for d in domains
        ],
        "tag_rows": [{"tag": t, "default_color": default_tag_color(t)} for t in tags],
    }
