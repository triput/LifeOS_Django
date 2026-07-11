# Generated manually for P3 calendar pull

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0001_v2_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="calendarintegration",
            name="last_sync_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="calendarintegration",
            name="last_sync_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddConstraint(
            model_name="calendarevent",
            constraint=models.UniqueConstraint(
                fields=("integration", "external_id"),
                name="uniq_calendar_event_external",
            ),
        ),
    ]
