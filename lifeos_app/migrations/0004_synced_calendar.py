# Multi-calendar selection per Google account

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0003_appsettings_google_oauth"),
    ]

    operations = [
        migrations.CreateModel(
            name="SyncedCalendar",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("calendar_id", models.CharField(max_length=255)),
                ("summary", models.CharField(max_length=255)),
                ("color", models.CharField(default="#8294AB", max_length=7)),
                ("is_primary", models.BooleanField(default=False)),
                ("sync_enabled", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "integration",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="calendars",
                        to="lifeos_app.calendarintegration",
                    ),
                ),
            ],
            options={
                "ordering": ["-is_primary", "summary"],
            },
        ),
        migrations.AddField(
            model_name="calendarevent",
            name="source_calendar",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="events",
                to="lifeos_app.syncedcalendar",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="calendarevent",
            name="uniq_calendar_event_external",
        ),
        migrations.AddConstraint(
            model_name="syncedcalendar",
            constraint=models.UniqueConstraint(
                fields=("integration", "calendar_id"),
                name="uniq_synced_calendar_per_integration",
            ),
        ),
        migrations.AddConstraint(
            model_name="calendarevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source_calendar__isnull", False)),
                fields=("source_calendar", "external_id"),
                name="uniq_calendar_event_per_source",
            ),
        ),
        migrations.AddConstraint(
            model_name="calendarevent",
            constraint=models.UniqueConstraint(
                condition=models.Q(("source_calendar__isnull", True)),
                fields=("integration", "external_id"),
                name="uniq_calendar_event_legacy",
            ),
        ),
    ]
