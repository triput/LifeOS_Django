# ==============================================================================
# File: lifeos_app/tests/test_p3_time_locale.py
# Description: BL-TIME-002 / BL-TIME-003 timezone and locale preference tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""IANA timezone picker, clock format, and unit system settings."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import AppSettings
from lifeos_app.services.settings_surface import save_general_settings
from lifeos_app.services.time_locale import (
    clock_format,
    iana_timezone_choices,
    is_valid_timezone,
    normalize_timezone,
)


class TimeLocaleHelperTests(TestCase):
    def test_iana_list_includes_phoenix(self):
        zones = iana_timezone_choices()
        self.assertIn("America/Phoenix", zones)
        self.assertEqual(zones[0], "America/Phoenix")

    def test_validate_timezone(self):
        self.assertTrue(is_valid_timezone("America/New_York"))
        self.assertFalse(is_valid_timezone("Not/AZone"))
        self.assertEqual(normalize_timezone("bogus", fallback="UTC"), "UTC")

    def test_clock_format(self):
        self.assertEqual(clock_format(use_24h=False), "g:i A")
        self.assertEqual(clock_format(use_24h=True), "H:i")
        self.assertEqual(clock_format(use_24h=False, short=True), "g:i")


class TimeLocaleSettingsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_general_tab_shows_locale_controls(self):
        response = self.client.get(reverse("canvas-settings"), {"tab": "general"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "iana-timezone-list")
        self.assertContains(response, "Detect timezone")
        self.assertContains(response, "24-hour clock")
        self.assertContains(response, "Imperial units")

    def test_save_timezone_and_locale_flags(self):
        result = save_general_settings(
            timezone="America/New_York",
            scheduler_buffer_minutes=15,
            auto_detect_location=True,
            use_24h_time=True,
            use_imperial=False,
        )
        self.assertTrue(result.ok)
        solo = AppSettings.get_solo()
        self.assertEqual(solo.timezone, "America/New_York")
        self.assertTrue(solo.auto_detect_location)
        self.assertTrue(solo.use_24h_time)
        self.assertFalse(solo.use_imperial)

    def test_reject_invalid_timezone(self):
        result = save_general_settings(
            timezone="Mars/Olympus",
            scheduler_buffer_minutes=10,
        )
        self.assertFalse(result.ok)
        self.assertIn("Unknown timezone", result.message)

    def test_htmx_save_locale(self):
        response = self.client.post(
            reverse("settings-general-save"),
            {
                "timezone": "UTC",
                "scheduler_buffer_minutes": "10",
                "settings_tab": "general",
                "use_24h_time": "on",
                "use_imperial": "on",
                "auto_detect_location": "on",
                "location_name": "Phoenix, AZ",
                "latitude": "33.66",
                "longitude": "-112.34",
                "weather_provider": "auto",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "General settings saved")
        solo = AppSettings.get_solo()
        self.assertEqual(solo.timezone, "UTC")
        self.assertTrue(solo.use_24h_time)
        self.assertTrue(solo.auto_detect_location)

    def test_context_exposes_clock_format(self):
        solo = AppSettings.get_solo()
        solo.use_24h_time = True
        solo.save(update_fields=["use_24h_time", "updated_at"])
        response = self.client.get(reverse("canvas-plan"))
        self.assertEqual(response.context["clock_format"], "H:i")
        self.assertEqual(response.context["clock_format_short"], "H:i")
        # Seeded allocation times render in 24h (e.g. 13:22)
        self.assertRegex(response.content.decode(), r"\d{2}:\d{2}")
