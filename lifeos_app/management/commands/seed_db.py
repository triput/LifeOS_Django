# ==============================================================================
# File: lifeos_app/management/commands/seed_db.py
# Description: Alias for seed_data (backward-compatible command name)
# Component: Core / Database Seeding
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Alias entry point — delegates to seed_data."""

from lifeos_app.management.commands.seed_data import Command as SeedDataCommand


class Command(SeedDataCommand):
    help = "Alias for seed_data — comprehensive LifeOS V2 test dataset."
