# ==============================================================================
# File: lifeos_app/services/dock.py
# Description: Session-backed drawer dock (FR-UI-004, FR-UI-005)
# Component: Services / Dock
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Minimized drawer contexts stored in signed session — LRU capped at 5."""

from __future__ import annotations

import secrets
from typing import Any

from django.utils import timezone

DOCK_SESSION_KEY = "lifeos_dock_entries"
MAX_DOCK_ENTRIES = 5


def _entries(request) -> list[dict[str, Any]]:
    return list(request.session.get(DOCK_SESSION_KEY, []))


def _save(request, entries: list[dict[str, Any]]) -> None:
    request.session[DOCK_SESSION_KEY] = entries[-MAX_DOCK_ENTRIES:]
    request.session.modified = True


def dock_list(request) -> list[dict[str, Any]]:
    return _entries(request)


def dock_minimize(request, kind: str, obj_id: int, label: str) -> str:
    """Push a drawer context onto the dock; return its token."""
    entries = [e for e in _entries(request) if not (e["kind"] == kind and e["id"] == obj_id)]
    token = secrets.token_urlsafe(8)
    entries.append(
        {
            "token": token,
            "kind": kind,
            "id": obj_id,
            "label": label[:48],
            "at": timezone.now().isoformat(),
        }
    )
    _save(request, entries)
    return token


def dock_pop(request, token: str) -> dict[str, Any] | None:
    """Remove and return a dock entry by token."""
    entries = _entries(request)
    match = next((e for e in entries if e["token"] == token), None)
    if match:
        _save(request, [e for e in entries if e["token"] != token])
    return match


def dock_remove(request, kind: str, obj_id: int) -> None:
    _save(request, [e for e in _entries(request) if not (e["kind"] == kind and e["id"] == obj_id)])
