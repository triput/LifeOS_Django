# Generated migration for Google OAuth fields on AppSettings

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0002_calendar_sync_meta"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="google_oauth_client_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="google_oauth_client_secret",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="google_oauth_redirect_uri",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional. Leave blank to auto-detect from the current site URL.",
                max_length=512,
            ),
        ),
    ]
