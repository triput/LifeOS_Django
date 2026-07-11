# ==============================================================================
# File: lifeos_app/services/tags.py
# Description: Tag resolution for capture and triage @tokens
# Component: Services
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Resolve @tag tokens to Tag records."""

from lifeos_app.models import Tag


def resolve_tag(token: str) -> Tag:
    """Find tag by name (case-insensitive) or create with token as name."""
    normalized = token.strip().lower()
    tag = Tag.objects.filter(name__iexact=normalized).first()
    if tag:
        return tag
    return Tag.objects.create(name=normalized, color="#8294AB")
