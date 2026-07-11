# ==============================================================================
# File: lifeos_app/migrations/0018_polish_notes_calendar.py
# Description: Container notes, calendar color lock, event description (polish)
# Component: Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-11
# Last Update: 2026-07-11
# ==============================================================================

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0017_calendar_push"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspacecontainer",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="syncedcalendar",
            name="color_locked",
            field=models.BooleanField(
                default=False,
                help_text="When True, Refresh list keeps the owner-chosen color.",
            ),
        ),
        migrations.AddField(
            model_name="calendarevent",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
