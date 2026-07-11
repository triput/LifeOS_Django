# ==============================================================================
# File: lifeos_app/tests/test_p3_telemetry_bands.py
# Description: BL-TELE-002 / BL-TELE-003 telemetry color band tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Weather heat and Kp color band resolution + Settings persistence."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from lifeos_app.models import AppSettings, SystemEnums
from lifeos_app.services.settings_surface import save_general_settings
from lifeos_app.services.telemetry.bands import (
    fahrenheit_to_celsius,
    resolve_kp_band,
    resolve_weather_band,
    weather_bands_for_display,
)
from lifeos_app.services.telemetry.space_weather import SpaceWeatherSnapshot
from lifeos_app.services.telemetry.weather import WeatherSnapshot


class BandResolutionTests(TestCase):
    def test_weather_bands_default_fahrenheit_display(self):
        """Defaults are °C in DB; with imperial, compare against °F temps."""
        solo = AppSettings.get_solo()
        solo.use_imperial = True
        solo.weather_band_cold_max = 10.0
        solo.weather_band_moderate_max = 23.9
        solo.weather_band_warm_max = 32.2
        solo.save()
        self.assertEqual(resolve_weather_band(40, solo).key, "blue")
        self.assertEqual(resolve_weather_band(60, solo).key, "green")
        self.assertEqual(resolve_weather_band(80, solo).key, "yellow")
        self.assertEqual(resolve_weather_band(95, solo).key, "red")
        self.assertIsNone(resolve_weather_band(None, solo))

    def test_weather_bands_metric(self):
        solo = AppSettings.get_solo()
        solo.use_imperial = False
        solo.weather_band_cold_max = 10.0
        solo.weather_band_moderate_max = 23.9
        solo.weather_band_warm_max = 32.2
        solo.save()
        self.assertEqual(resolve_weather_band(5, solo).key, "blue")
        self.assertEqual(resolve_weather_band(15, solo).key, "green")
        self.assertEqual(resolve_weather_band(28, solo).key, "yellow")
        self.assertEqual(resolve_weather_band(35, solo).key, "red")

    def test_kp_bands(self):
        solo = AppSettings.get_solo()
        self.assertEqual(resolve_kp_band(1.0, solo).key, "blue")
        self.assertEqual(resolve_kp_band(4.0, solo).key, "green")
        self.assertEqual(resolve_kp_band(6.0, solo).key, "yellow")
        self.assertEqual(resolve_kp_band(8.0, solo).key, "red")


class BandSettingsAndHudTests(TestCase):
    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_save_band_thresholds_imperial_stores_celsius(self):
        result = save_general_settings(
            timezone="America/Phoenix",
            scheduler_buffer_minutes=10,
            use_imperial=True,
            weather_band_cold_max=45,
            weather_band_moderate_max=70,
            weather_band_warm_max=88,
            kp_band_blue_max=2.5,
            kp_band_green_max=4.5,
            kp_band_yellow_max=6.5,
        )
        self.assertTrue(result.ok)
        solo = AppSettings.get_solo()
        self.assertAlmostEqual(solo.weather_band_cold_max, fahrenheit_to_celsius(45), places=1)
        self.assertAlmostEqual(solo.weather_band_warm_max, fahrenheit_to_celsius(88), places=1)
        self.assertEqual(solo.kp_band_yellow_max, 6.5)

    def test_save_band_thresholds_metric_stores_celsius(self):
        result = save_general_settings(
            timezone="America/Phoenix",
            scheduler_buffer_minutes=10,
            use_imperial=False,
            weather_band_cold_max=5,
            weather_band_moderate_max=18,
            weather_band_warm_max=28,
        )
        self.assertTrue(result.ok)
        solo = AppSettings.get_solo()
        self.assertFalse(solo.use_imperial)
        self.assertEqual(solo.weather_band_cold_max, 5.0)
        self.assertEqual(solo.weather_band_moderate_max, 18.0)
        self.assertEqual(solo.weather_band_warm_max, 28.0)

    def test_settings_general_shows_display_unit_values(self):
        solo = AppSettings.get_solo()
        solo.use_imperial = True
        solo.weather_band_cold_max = 10.0
        solo.weather_band_moderate_max = 23.9
        solo.weather_band_warm_max = 32.2
        solo.save()
        cold_f, _, _ = weather_bands_for_display(
            use_imperial=True, cold_c=10.0, moderate_c=23.9, warm_c=32.2
        )
        response = self.client.get(reverse("canvas-settings"), {"tab": "general"})
        self.assertContains(response, "Telemetry color bands")
        self.assertContains(response, "weather_band_cold_max")
        self.assertContains(response, str(cold_f))
        self.assertContains(response, "°F")

    def test_settings_metric_shows_celsius_label(self):
        solo = AppSettings.get_solo()
        solo.use_imperial = False
        solo.save(update_fields=["use_imperial"])
        response = self.client.get(reverse("canvas-settings"), {"tab": "general"})
        self.assertContains(response, "°C")

    def test_reset_weather_bands_to_defaults(self):
        from lifeos_app.services.settings_surface import reset_telemetry_bands
        from lifeos_app.services.telemetry.bands import default_weather_bands_c

        solo = AppSettings.get_solo()
        solo.weather_band_cold_max = 1.0
        solo.weather_band_moderate_max = 2.0
        solo.weather_band_warm_max = 3.0
        solo.save()
        result = reset_telemetry_bands(kind="weather")
        self.assertTrue(result.ok)
        solo.refresh_from_db()
        self.assertEqual(
            (solo.weather_band_cold_max, solo.weather_band_moderate_max, solo.weather_band_warm_max),
            default_weather_bands_c(),
        )

    def test_reset_kp_bands_htmx(self):
        solo = AppSettings.get_solo()
        solo.kp_band_blue_max = 0.5
        solo.kp_band_green_max = 1.0
        solo.kp_band_yellow_max = 1.5
        solo.save()
        response = self.client.post(
            reverse("settings-bands-reset"),
            {"kind": "kp", "settings_tab": "general"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kp band thresholds reset")
        solo.refresh_from_db()
        self.assertEqual(solo.kp_band_blue_max, 3.0)
        self.assertEqual(solo.kp_band_green_max, 5.0)
        self.assertEqual(solo.kp_band_yellow_max, 7.0)

    def test_settings_shows_default_hints(self):
        response = self.client.get(reverse("canvas-settings"), {"tab": "general"})
        self.assertContains(response, "Weather defaults:")
        self.assertContains(response, "Kp defaults:")
        self.assertContains(response, "Reset all")

    @patch("lifeos_app.services.telemetry.hud.fetch_space_weather")
    @patch("lifeos_app.services.telemetry.hud.fetch_weather")
    def test_hud_includes_band_colors(self, mock_weather, mock_space):
        mock_weather.return_value = WeatherSnapshot(
            temperature=95.0,
            temperature_unit="F",
            humidity=10,
            wind_speed=5.0,
            wind_unit="mph",
            condition_label="Clear",
            condition_code=0,
            provider=SystemEnums.WeatherProvider.OPEN_METEO,
            fetched_at=timezone.now(),
        )
        mock_space.return_value = SpaceWeatherSnapshot(
            kp_index=8.0,
            label="Storm",
            fetched_at=timezone.now(),
        )
        response = self.client.get(reverse("telemetry-hud"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "95°F")
        self.assertContains(response, "Hot")
        self.assertContains(response, "#C45C4A")
        self.assertContains(response, "Storm")
