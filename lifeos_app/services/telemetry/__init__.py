# ==============================================================================
# File: lifeos_app/services/telemetry/__init__.py
# Description: Telemetry service package (ENG-TELE)
# Component: Services / Telemetry
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Lazy-loaded environmental telemetry for the Home Tier 4 HUD."""

from lifeos_app.services.telemetry.hud import build_telemetry_hud

__all__ = ["build_telemetry_hud"]
