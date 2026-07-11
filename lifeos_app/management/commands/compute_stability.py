# ==============================================================================
# File: lifeos_app/management/commands/compute_stability.py
# Description: Cron/CLI entry for daily Stability Index rollup
# Component: Management / Stability
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Compute System Stability Index for today (or --date)."""

from datetime import date

from django.core.management.base import BaseCommand

from lifeos_app.services.stability import compute_stability_for_date, today_local


class Command(BaseCommand):
    help = "Compute StabilitySnapshot for today (owner timezone) or --date YYYY-MM-DD."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default="",
            help="Local date YYYY-MM-DD (default: owner today)",
        )

    def handle(self, *args, **options):
        raw = (options.get("date") or "").strip()
        if raw:
            local_date = date.fromisoformat(raw)
        else:
            local_date = today_local()
        snap = compute_stability_for_date(local_date)
        self.stdout.write(
            self.style.SUCCESS(
                f"Stability {snap.date}: score={snap.index_score} band={snap.band} "
                f"completions={snap.completions_count} focus_s={snap.focus_seconds} "
                f"streak={snap.streak_days}"
            )
        )
