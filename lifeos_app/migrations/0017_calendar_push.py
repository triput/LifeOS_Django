# ==============================================================================
# Migration: 0017_calendar_push
# ==============================================================================

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0016_recurrence_ends_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="calendar_push_enabled",
            field=models.BooleanField(
                default=False,
                help_text="P5-03: push LifeOS allocations to Google Calendar (requires reconnect for write scope).",
            ),
        ),
        migrations.AddField(
            model_name="scheduledallocation",
            name="external_event_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Google event id when pushed (P5-03).",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="scheduledallocation",
            name="push_calendar",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="pushed_allocations",
                to="lifeos_app.syncedcalendar",
            ),
        ),
    ]
