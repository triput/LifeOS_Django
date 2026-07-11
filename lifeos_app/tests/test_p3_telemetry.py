# ==============================================================================
# File: lifeos_app/tests/test_p3_telemetry.py
# Description: P3-ENG-TELE / BL-TELE-001 telemetry tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Telemetry HUD — weather provider resolution, adapters, lazy-load endpoint."""

import json
from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from lifeos_app.models import AppSettings, SystemEnums
from lifeos_app.services.telemetry.space_weather import SpaceWeatherSnapshot, fetch_space_weather
from lifeos_app.services.telemetry.weather import (
    WeatherSnapshot,
    fetch_weather,
    is_us_location,
    resolve_weather_provider,
)


class WeatherProviderTests(TestCase):
    def test_us_location_bbox(self):
        self.assertTrue(is_us_location(33.66, -112.34))
        self.assertTrue(is_us_location(64.0, -147.0))
        self.assertFalse(is_us_location(51.5, -0.1))

    def test_resolve_auto_us_uses_nws(self):
        solo = AppSettings.get_solo()
        solo.weather_provider = SystemEnums.WeatherProvider.AUTO
        solo.latitude = 33.66
        solo.longitude = -112.34
        self.assertEqual(resolve_weather_provider(solo), SystemEnums.WeatherProvider.NWS)

    def test_resolve_auto_non_us_uses_open_meteo(self):
        solo = AppSettings.get_solo()
        solo.weather_provider = SystemEnums.WeatherProvider.AUTO
        solo.latitude = 51.5
        solo.longitude = -0.1
        self.assertEqual(resolve_weather_provider(solo), SystemEnums.WeatherProvider.OPEN_METEO)

    def test_owner_override(self):
        solo = AppSettings.get_solo()
        solo.weather_provider = SystemEnums.WeatherProvider.OPEN_METEO
        solo.latitude = 33.66
        solo.longitude = -112.34
        self.assertEqual(resolve_weather_provider(solo), SystemEnums.WeatherProvider.OPEN_METEO)


class WeatherAdapterTests(TestCase):
    def setUp(self):
        cache.clear()
        solo = AppSettings.get_solo()
        solo.latitude = 33.66
        solo.longitude = -112.34
        solo.weather_provider = SystemEnums.WeatherProvider.OPEN_METEO
        solo.save(update_fields=["latitude", "longitude", "weather_provider", "updated_at"])

    @patch("lifeos_app.services.telemetry.weather._http_json")
    def test_fetch_open_meteo_normalized(self, mock_http):
        mock_http.return_value = {
            "current": {
                "temperature_2m": 74.2,
                "relative_humidity_2m": 18,
                "weather_code": 0,
                "wind_speed_10m": 6.5,
            }
        }
        snapshot = fetch_weather()
        self.assertEqual(snapshot.temperature, 74.2)
        self.assertEqual(snapshot.temperature_unit, "F")
        self.assertEqual(snapshot.condition_label, "Clear")
        self.assertEqual(snapshot.provider, SystemEnums.WeatherProvider.OPEN_METEO)
        mock_http.assert_called_once()

    @patch("lifeos_app.services.telemetry.weather._http_json")
    def test_fetch_uses_cache(self, mock_http):
        cached = WeatherSnapshot(
            temperature=70.0,
            temperature_unit="F",
            humidity=20,
            wind_speed=5.0,
            wind_unit="mph",
            condition_label="Clear",
            condition_code=0,
            provider=SystemEnums.WeatherProvider.OPEN_METEO,
            fetched_at=timezone.now(),
        )
        cache.set(
            "telemetry:weather:open_meteo:33.6600:-112.3400:imperial",
            cached.to_cache(),
            1800,
        )
        snapshot = fetch_weather()
        self.assertEqual(snapshot.temperature, 70.0)
        mock_http.assert_not_called()

    @patch("lifeos_app.services.telemetry.weather._fetch_provider")
    def test_fetch_failure_returns_placeholder(self, mock_fetch):
        mock_fetch.side_effect = TimeoutError("slow")
        snapshot = fetch_weather()
        self.assertEqual(snapshot.condition_label, "Unavailable")


class SpaceWeatherTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch("lifeos_app.services.telemetry.space_weather._fetch_kp_index")
    def test_fetch_space_weather_caches(self, mock_fetch):
        mock_fetch.return_value = SpaceWeatherSnapshot(
            kp_index=2.0,
            label="Calm",
            fetched_at=timezone.now(),
        )
        first = fetch_space_weather()
        second = fetch_space_weather()
        self.assertEqual(first.kp_index, 2.0)
        self.assertEqual(second.label, "Calm")
        mock_fetch.assert_called_once()

    @patch("lifeos_app.services.telemetry.space_weather.urllib.request.urlopen")
    def test_parse_current_swpc_dict_rows(self, mock_urlopen):
        from lifeos_app.services.telemetry.space_weather import _fetch_kp_index

        payload = json.dumps(
            [
                {"time_tag": "2026-07-10T09:00:00", "Kp": 1.0, "a_running": 4, "station_count": 7},
                {"time_tag": "2026-07-10T12:00:00", "Kp": 2.33, "a_running": 9, "station_count": 8},
            ]
        ).encode("utf-8")
        mock_resp = mock_urlopen.return_value.__enter__.return_value
        mock_resp.read.return_value = payload
        snapshot = _fetch_kp_index()
        self.assertEqual(snapshot.kp_index, 2.33)
        self.assertEqual(snapshot.label, "Calm")

    @patch("lifeos_app.services.telemetry.space_weather.urllib.request.urlopen")
    def test_parse_legacy_list_rows(self, mock_urlopen):
        from lifeos_app.services.telemetry.space_weather import _fetch_kp_index

        payload = json.dumps(
            [
                ["time_tag", "Kp", "a_running", "station_count"],
                ["2026-07-10T12:00:00", "3.00", "12", "8"],
            ]
        ).encode("utf-8")
        mock_resp = mock_urlopen.return_value.__enter__.return_value
        mock_resp.read.return_value = payload
        snapshot = _fetch_kp_index()
        self.assertEqual(snapshot.kp_index, 3.0)

    @patch("lifeos_app.services.telemetry.space_weather._fetch_kp_index")
    def test_fetch_failure_returns_placeholder(self, mock_fetch):
        mock_fetch.side_effect = KeyError(1)
        snapshot = fetch_space_weather()
        self.assertEqual(snapshot.label, "Unavailable")
        self.assertIsNone(snapshot.kp_index)


class TelemetryHudViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")
        cache.clear()

    @patch("lifeos_app.services.telemetry.hud.fetch_space_weather")
    @patch("lifeos_app.services.telemetry.hud.fetch_weather")
    def test_telemetry_hud_endpoint(self, mock_weather, mock_space):
        mock_weather.return_value = WeatherSnapshot(
            temperature=74.0,
            temperature_unit="F",
            humidity=20,
            wind_speed=6.0,
            wind_unit="mph",
            condition_label="Clear",
            condition_code=0,
            provider=SystemEnums.WeatherProvider.NWS,
            fetched_at=datetime.now(),
        )
        mock_space.return_value = SpaceWeatherSnapshot(
            kp_index=2.0,
            label="Calm",
            fetched_at=datetime.now(),
        )
        response = self.client.get(reverse("telemetry-hud"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "74°F")
        self.assertContains(response, "Space weather")
        self.assertContains(response, "Kp 2")

    def test_home_includes_lazy_telemetry_skeleton(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="telemetry-hud"')
        self.assertContains(response, reverse("telemetry-hud"))
