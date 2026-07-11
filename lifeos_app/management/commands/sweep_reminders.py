# ==============================================================================
# File: lifeos_app/management/commands/sweep_reminders.py
# Description: Cron-friendly reminder dispatch sweep (ENG-NOTIFY)
# Component: Management / Jobs
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Run outbound reminder sweep — `python manage.py sweep_reminders`."""

from django.core.management.base import BaseCommand

from lifeos_app.services.notify import sweep_reminders


class Command(BaseCommand):
    help = "Sweep due ReminderDispatch rows and POST to configured webhook."

    def handle(self, *args, **options):
        result = sweep_reminders()
        self.stdout.write(
            self.style.SUCCESS(
                f"examined={result.examined} sent={result.sent} "
                f"failed={result.failed} skipped={result.skipped}"
            )
        )
