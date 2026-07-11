# ==============================================================================
# File: lifeos_app/management/commands/run_beat_jobs.py
# Description: Run Celery Beat jobs once without a worker (cron / debug fallback)
# Component: Management / Jobs
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Execute scheduled job bodies synchronously — useful when Redis/Celery is down."""

from django.core.management.base import BaseCommand

from lifeos_app.tasks import (
    compute_stability_task,
    sweep_reminders_task,
    warm_telemetry_task,
)


class Command(BaseCommand):
    help = (
        "Run P5-04 Beat job bodies once (reminders, telemetry, optional stability). "
        "Prefer `celery -A lifeos_django worker -B` when Redis is available."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--stability",
            action="store_true",
            help="Also run compute_stability (normally daily via Beat).",
        )
        parser.add_argument(
            "--reminders-only",
            action="store_true",
            help="Only sweep reminders.",
        )
        parser.add_argument(
            "--telemetry-only",
            action="store_true",
            help="Only warm telemetry caches.",
        )

    def handle(self, *args, **options):
        reminders_only = options["reminders_only"]
        telemetry_only = options["telemetry_only"]
        run_all = not reminders_only and not telemetry_only

        if run_all or reminders_only:
            result = sweep_reminders_task.run()
            self.stdout.write(self.style.SUCCESS(f"sweep_reminders: {result}"))
        if run_all or telemetry_only:
            result = warm_telemetry_task.run()
            self.stdout.write(self.style.SUCCESS(f"warm_telemetry: {result}"))
        if options["stability"]:
            result = compute_stability_task.run()
            self.stdout.write(self.style.SUCCESS(f"compute_stability: {result}"))
