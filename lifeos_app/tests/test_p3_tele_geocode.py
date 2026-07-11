# ==============================================================================
# File: lifeos_app/tests/test_p3_tele_geocode.py
# Description: BL-TELE-005 typed place → lat/lon geocode tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Forward geocode parse + Settings resolve endpoint."""

from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.services.telemetry.geocode import geocode_place, parse_place_label


class ParsePlaceLabelTests(TestCase):
    def test_us_city_state(self):
        q = parse_place_label("Phoenix, AZ")
        self.assertIsNotNone(q)
        self.assertEqual(q.name, "Phoenix")
        self.assertEqual(q.admin1, "Arizona")
        self.assertEqual(q.country_code, "US")

    def test_international_three_part(self):
        q = parse_place_label("London, England, UK")
        self.assertEqual(q.name, "London")
        self.assertEqual(q.admin1, "England")
        self.assertEqual(q.country_code, "GB")

    def test_city_country_two_part(self):
        q = parse_place_label("Paris, France")
        self.assertEqual(q.name, "Paris")
        self.assertEqual(q.country_code, "FR")
        self.assertEqual(q.admin1, "")


class GeocodePlaceTests(TestCase):
    @patch("lifeos_app.services.telemetry.geocode._http_search")
    def test_geocode_picks_admin1_match(self, mock_search):
        mock_search.return_value = [
            {
                "name": "Phoenix",
                "latitude": 33.4484,
                "longitude": -112.074,
                "admin1": "Arizona",
                "country_code": "US",
                "country": "United States",
            },
            {
                "name": "Phoenix",
                "latitude": 42.0,
                "longitude": -71.0,
                "admin1": "New York",
                "country_code": "US",
                "country": "United States",
            },
        ]
        result = geocode_place("Phoenix, AZ")
        self.assertTrue(result.ok)
        self.assertEqual(result.hit.admin1, "Arizona")
        self.assertAlmostEqual(result.hit.latitude, 33.4484, places=3)

    @patch("lifeos_app.services.telemetry.geocode._http_search")
    def test_geocode_no_results(self, mock_search):
        mock_search.return_value = []
        result = geocode_place("Nowhereville, ZZ")
        self.assertFalse(result.ok)


class GeocodeEndpointTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_settings_shows_resolve_control(self):
        response = self.client.get(reverse("canvas-settings"), {"tab": "general"})
        self.assertContains(response, "Resolve coordinates")
        self.assertContains(response, "lifeosResolveLocationFromLabel")

    @patch("lifeos_app.services.telemetry.geocode._http_search")
    def test_geocode_endpoint(self, mock_search):
        mock_search.return_value = [
            {
                "name": "Phoenix",
                "latitude": 33.4484,
                "longitude": -112.074,
                "admin1": "Arizona",
                "country_code": "US",
                "country": "United States",
            }
        ]
        response = self.client.post(
            reverse("settings-geocode"),
            {"location_name": "Phoenix, AZ"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertAlmostEqual(data["latitude"], 33.4484, places=3)
        self.assertIn("Arizona", data["label"])

    def test_geocode_empty_rejected(self):
        response = self.client.post(reverse("settings-geocode"), {"location_name": ""})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
