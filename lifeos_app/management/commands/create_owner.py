# ==============================================================================
# File: lifeos_app/management/commands/create_owner.py
# Description: CLI command to create or reset the LifeOS owner superuser
# Component: Core / Management
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Create the single-owner superuser account from the command line."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from lifeos_app.services.owner import create_owner_user, owner_exists


class Command(BaseCommand):
    help = "Create or reset the LifeOS owner (superuser) account."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Owner username")
        parser.add_argument("--password", required=True, help="Owner password")
        parser.add_argument("--email", default="", help="Owner email (optional)")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Update credentials even if an owner already exists.",
        )

    def handle(self, *args, **options):
        if owner_exists() and not options["force"]:
            raise CommandError(
                "Owner account already exists. Use --force to reset credentials, "
                "or visit /setup/ only works when no owner exists."
            )
        try:
            user, created = create_owner_user(
                options["username"],
                options["password"],
                options["email"],
                force=options["force"],
            )
        except ValidationError as exc:
            raise CommandError(exc.messages[0] if exc.messages else str(exc)) from exc

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} owner account '{user.username}'."))
