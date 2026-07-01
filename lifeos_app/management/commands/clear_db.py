# ==============================================================================
# File: lifeos_app/management/commands/clear_db.py
# Description: Django management command to clear user data while keeping settings/users intact
# Component: Core / Database Clearing
# Version: 1.0 (Gold Master)
# Created: 2026-07-01
# Last Update: 2026-07-01
# ==============================================================================

from django.core.management.base import BaseCommand
from lifeos_app.models import (
    WorkspaceContainer, ExecutionItem, Tag, DomainCategory, 
    TimeAvailabilityBlock, RecurringConfig, Certification,
    GoogleCalendar, NotionIntegration, CalendarIntegration
)

class Command(BaseCommand):
    help = 'Clears all operational user data (Tasks, Projects, Epics, Tags, Integrations) while keeping users and core AppSettings intact.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Bypasses confirmation prompt and clears database immediately.',
        )

    def handle(self, *args, **options):
        if not options['force']:
            self.stdout.write(self.style.WARNING(
                "WARNING: This will permanently delete all your operational data (Epics, Projects, Tasks, Tags, and Calendar integrations).\n"
                "Your User accounts and core System Settings will NOT be deleted."
            ))
            confirm = input("Are you absolutely sure you want to proceed? (yes/no): ")
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.ERROR("Database clearing aborted."))
                return

        self.stdout.write(self.style.WARNING("Clearing database operational data..."))
        
        try:
            # Delete in order of dependency to prevent database integrity errors
            RecurringConfig.objects.all().delete()
            TimeAvailabilityBlock.objects.all().delete()
            ExecutionItem.objects.all().delete()
            WorkspaceContainer.objects.all().delete()
            DomainCategory.objects.all().delete()
            Tag.objects.all().delete()
            Certification.objects.all().delete()
            GoogleCalendar.objects.all().delete()
            NotionIntegration.objects.all().delete()
            CalendarIntegration.objects.all().delete()
            
            self.stdout.write(self.style.SUCCESS("Database successfully cleared of operational data! Ready for real data."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred while clearing the database: {e}"))
