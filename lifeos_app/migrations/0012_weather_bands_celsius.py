# ==============================================================================
# File: lifeos_app/migrations/0012_weather_bands_celsius.py
# Description: Store weather band cutoffs in °C; convert legacy °F values (DEF-P33-005)
# Component: Data / Migrations
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================

from django.db import migrations, models


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return round((float(fahrenheit) - 32.0) * 5.0 / 9.0, 1)


def forwards_convert_f_to_c(apps, schema_editor):
    """Prior defaults/UI treated cutoffs as °F — convert existing rows to °C."""
    AppSettings = apps.get_model("lifeos_app", "AppSettings")
    for solo in AppSettings.objects.all():
        solo.weather_band_cold_max = fahrenheit_to_celsius(solo.weather_band_cold_max)
        solo.weather_band_moderate_max = fahrenheit_to_celsius(solo.weather_band_moderate_max)
        solo.weather_band_warm_max = fahrenheit_to_celsius(solo.weather_band_warm_max)
        solo.save(
            update_fields=[
                "weather_band_cold_max",
                "weather_band_moderate_max",
                "weather_band_warm_max",
            ]
        )


def backwards_convert_c_to_f(apps, schema_editor):
    AppSettings = apps.get_model("lifeos_app", "AppSettings")
    for solo in AppSettings.objects.all():
        solo.weather_band_cold_max = round(float(solo.weather_band_cold_max) * 9.0 / 5.0 + 32.0, 1)
        solo.weather_band_moderate_max = round(
            float(solo.weather_band_moderate_max) * 9.0 / 5.0 + 32.0, 1
        )
        solo.weather_band_warm_max = round(float(solo.weather_band_warm_max) * 9.0 / 5.0 + 32.0, 1)
        solo.save(
            update_fields=[
                "weather_band_cold_max",
                "weather_band_moderate_max",
                "weather_band_warm_max",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("lifeos_app", "0011_telemetry_band_thresholds"),
    ]

    operations = [
        migrations.RunPython(forwards_convert_f_to_c, backwards_convert_c_to_f),
        migrations.AlterField(
            model_name="appsettings",
            name="weather_band_cold_max",
            field=models.FloatField(default=10.0),
        ),
        migrations.AlterField(
            model_name="appsettings",
            name="weather_band_moderate_max",
            field=models.FloatField(default=23.9),
        ),
        migrations.AlterField(
            model_name="appsettings",
            name="weather_band_warm_max",
            field=models.FloatField(default=32.2),
        ),
    ]
