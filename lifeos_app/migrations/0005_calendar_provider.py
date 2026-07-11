# Calendar provider field for multi-vendor ENG-CAL

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0004_synced_calendar"),
    ]

    operations = [
        migrations.AddField(
            model_name="calendarintegration",
            name="provider",
            field=models.CharField(
                choices=[("google", "Google Calendar"), ("microsoft", "Microsoft 365 / Outlook")],
                default="google",
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="calendarintegration",
            constraint=models.UniqueConstraint(
                condition=models.Q(("user_email__gt", "")),
                fields=("provider", "user_email"),
                name="uniq_calendar_integration_provider_email",
            ),
        ),
    ]
