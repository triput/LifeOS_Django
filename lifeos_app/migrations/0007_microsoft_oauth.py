# Generated manually for BL-CAL-001 — Microsoft Graph OAuth client fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0006_notification_channel"),
    ]

    operations = [
        migrations.AddField(
            model_name="appsettings",
            name="microsoft_oauth_client_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="microsoft_oauth_client_secret",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="appsettings",
            name="microsoft_oauth_redirect_uri",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
    ]
