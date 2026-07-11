# ==============================================================================
# Migration: 0013_container_extra_actual_seconds
# ==============================================================================

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0012_weather_bands_celsius"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspacecontainer",
            name="extra_actual_seconds",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Manual time not attributable to a leaf (FR-FOCUS-002).",
            ),
        ),
    ]
