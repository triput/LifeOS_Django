# ==============================================================================
# File: lifeos_app/management/commands/sync_calendar.py
# Description: Cron-friendly Google Calendar pull (ENG-CAL)
# Component: Management / Jobs
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Pull Google Calendar events — `python manage.py sync_calendar`."""

from django.core.management.base import BaseCommand

from lifeos_app.services.calendar_sync import pull_calendar


class Command(BaseCommand):
    help = "Pull events from Google Calendar into CalendarEvent rows."

    def handle(self, *args, **options):
        result = pull_calendar()
        if result.ok:
            self.stdout.write(self.style.SUCCESS(result.message))
        else:
            self.stdout.write(self.style.ERROR(result.message))
