# ==============================================================================
# Migration: 0016_recurrence_ends_at
# ==============================================================================

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0015_merge_0014_leaves"),
    ]

    operations = [
        migrations.AddField(
            model_name="recurrencerule",
            name="ends_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Optional series end (BL-REC-002); no spawn after this local day.",
                null=True,
            ),
        ),
    ]
