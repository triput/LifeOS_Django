# Migrate legacy theme_mode values to BL-UI-003 slugs

from django.db import migrations, models


def forward_theme_slugs(apps, schema_editor):
    AppSettings = apps.get_model("lifeos_app", "AppSettings")
    mapping = {
        "Dark": "hybrid_dark",
        "dark": "hybrid_dark",
        "Hybrid Dark": "hybrid_dark",
    }
    for row in AppSettings.objects.all():
        if row.theme_mode in mapping:
            row.theme_mode = mapping[row.theme_mode]
            row.save(update_fields=["theme_mode"])


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0007_microsoft_oauth"),
    ]

    operations = [
        migrations.AlterField(
            model_name="appsettings",
            name="theme_mode",
            field=models.CharField(default="hybrid_dark", max_length=32),
        ),
        migrations.RunPython(forward_theme_slugs, migrations.RunPython.noop),
    ]
