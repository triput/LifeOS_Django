# ==============================================================================
# Migration: 0014_recurrence_starts_at
# ==============================================================================

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0013_container_extra_actual_seconds"),
    ]

    operations = [
        migrations.AddField(
            model_name="recurrencerule",
            name="starts_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Optional series start floor (BL-REC-001).",
                null=True,
            ),
        ),
    ]
