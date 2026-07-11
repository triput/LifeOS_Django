# ==============================================================================
# File: lifeos_app/tests/test_p3_tele_location.py
# Description: BL-TELE-004 weather location detect / cache invalidation tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Settings geolocation affordance + weather cache bust on coord change."""

from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import AppSettings, SystemEnums
from lifeos_app.services.settings_surface import save_general_settings
from lifeos_app.services.telemetry.weather import (
    _cache_key,
    invalidate_weather_cache_for_coords,
)


class WeatherLocationCacheTests(TestCase):
    def test_invalidate_weather_cache_for_coords(self):
        key = _cache_key(SystemEnums.WeatherProvider.OPEN_METEO, 33.66, -112.34, use_imperial=True)
        cache.set(key, {"temperature": 99}, 60)
        invalidate_weather_cache_for_coords(33.66, -112.34)
        self.assertIsNone(cache.get(key))

    def test_save_location_change_invalidates_cache(self):
        solo = AppSettings.get_solo()
        solo.latitude = 33.66
        solo.longitude = -112.34
        solo.save(update_fields=["latitude", "longitude"])
        old_key = _cache_key(
            SystemEnums.WeatherProvider.NWS, 33.66, -112.34, use_imperial=True
        )
        cache.set(old_key, {"temperature": 1}, 60)
        with patch(
            "lifeos_app.services.telemetry.weather.invalidate_weather_cache_for_coords"
        ) as mock_inv:
            result = save_general_settings(
                timezone="America/Phoenix",
                scheduler_buffer_minutes=10,
                location_name="Elsewhere",
                latitude=40.0,
                longitude=-105.0,
                use_imperial=True,
            )
        self.assertTrue(result.ok)
        self.assertGreaterEqual(mock_inv.call_count, 2)


class WeatherLocationSettingsUiTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_settings_shows_detect_location_control(self):
        response = self.client.get(reverse("canvas-settings"), {"tab": "general"})
        self.assertContains(response, "Detect my location for weather")
        self.assertContains(response, "settings-latitude")
        self.assertContains(response, "lifeosDetectWeatherLocation")
