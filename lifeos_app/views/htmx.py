# ==============================================================================
# File: lifeos_app/views/htmx.py
# Description: Shared HTMX response helpers (P5-09 refactor)
# Component: Views / HTMX
# Version: 1.0 (Gold Master)
# Created: 2026-07-11
# Last Update: 2026-07-11
# ==============================================================================
"""Common HX-Trigger payloads for cockpit fragment refresh."""

from __future__ import annotations

import json

from django.http import HttpResponse

# Home Tier 1–3 + Stability Index refresh after mutations.
COCKPIT_REFRESH = {"refreshHome": True, "refreshStability": True}


def set_hx_trigger(response: HttpResponse, *events: str, **flags: bool) -> HttpResponse:
    """Attach HX-Trigger — string events and/or boolean flag map."""
    payload: dict | str
    if flags and not events:
        payload = flags
    elif events and not flags:
        if len(events) == 1:
            payload = events[0]
        else:
            payload = {e: True for e in events}
    else:
        payload = {e: True for e in events}
        payload.update(flags)
    if isinstance(payload, str):
        response["HX-Trigger"] = payload
    else:
        response["HX-Trigger"] = json.dumps(payload)
    return response


def set_cockpit_refresh(response: HttpResponse, **extra: bool) -> HttpResponse:
    """Refresh Home + Stability, optionally merging extra trigger flags."""
    flags = {**COCKPIT_REFRESH, **extra}
    return set_hx_trigger(response, **flags)
