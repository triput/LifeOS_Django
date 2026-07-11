# Generated manually for BL-NOTIFY-001 — ntfy default webhook channel

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0005_calendar_provider"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="notification_channel",
            field=models.CharField(
                choices=[("ntfy", "ntfy"), ("gotify", "Gotify"), ("raw_json", "Raw JSON")],
                default="ntfy",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="reminderdispatch",
            name="channel",
            field=models.CharField(default="webhook_ntfy", max_length=64),
        ),
    ]
