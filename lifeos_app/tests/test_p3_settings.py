# ==============================================================================
# File: lifeos_app/tests/test_p3_settings.py
# Description: P3 Settings surface tests (SURF-SETTINGS round 3)
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""Settings canvas — notifications, OAuth client, availability CRUD, tabs."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import AppSettings, TimeAvailabilityBlock
from lifeos_app.services.settings_surface import save_google_oauth_settings, save_notification_settings


class SettingsViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_settings_page_renders(self):
        response = self.client.get(reverse("canvas-settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notifications")
        self.assertContains(response, 'role="tablist"')
        self.assertContains(response, "Appearance")
        self.assertContains(response, "Save general")
        self.assertNotContains(response, "Availability windows")

    def test_settings_tab_query_param(self):
        response = self.client.get(reverse("canvas-settings"), {"tab": "calendars"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-selected="true"')
        self.assertContains(response, "Outlook / Microsoft 365 OAuth")
        self.assertNotContains(response, "Save general")
        self.assertNotContains(response, "Save appearance")

    def test_htmx_save_preserves_tab(self):
        response = self.client.post(
            reverse("settings-general-save"),
            {
                "timezone": "America/Phoenix",
                "scheduler_buffer_minutes": "10",
                "settings_tab": "general",
                "use_imperial": "on",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "General settings saved")
        self.assertContains(response, "Save general")
        self.assertNotContains(response, "Save appearance")
        self.assertNotContains(response, "Availability windows")

    def test_htmx_tab_switch_returns_single_panel(self):
        response = self.client.get(
            reverse("canvas-settings"),
            {"tab": "notifications"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Save notifications")
        self.assertNotContains(response, "Save appearance")
        self.assertNotContains(response, "<!DOCTYPE")

    def test_htmx_save_returns_fragment_not_full_shell(self):
        """Regression: full-page HTMX swap nested the entire cockpit inside Settings."""
        response = self.client.post(
            reverse("settings-general-save"),
            {
                "timezone": "America/Phoenix",
                "scheduler_buffer_minutes": "10",
                "settings_tab": "general",
                "use_imperial": "on",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="settings-page"', content)
        self.assertNotIn("<!DOCTYPE", content)
        self.assertNotIn('id="main-canvas"', content)
        self.assertEqual(content.count("LifeOS COCKPIT"), 0)

    def test_save_notification_settings(self):
        response = self.client.post(
            reverse("settings-notifications-save"),
            {
                "notifications_enabled": "on",
                "notification_channel": "ntfy",
                "notification_webhook_url": "https://ntfy.example.com/lifeos",
                "notification_webhook_token": "secret",
                "reminder_lead_minutes": "30",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        solo = AppSettings.get_solo()
        self.assertTrue(solo.notifications_enabled)
        self.assertEqual(solo.notification_channel, "ntfy")
        self.assertEqual(solo.notification_webhook_url, "https://ntfy.example.com/lifeos")
        self.assertEqual(solo.reminder_lead_minutes, 30)

    def test_save_google_oauth_strips_quotes(self):
        result = save_google_oauth_settings(
            client_id="123456789012-abc.apps.googleusercontent.com",
            client_secret='"GOCSPX-quoted"',
            redirect_uri="",
        )
        self.assertTrue(result.ok)
        solo = AppSettings.get_solo()
        self.assertEqual(solo.google_oauth_client_secret, "GOCSPX-quoted")

    def test_create_and_delete_availability(self):
        before = TimeAvailabilityBlock.objects.count()
        response = self.client.post(
            reverse("settings-availability-create"),
            {
                "name": "Evening focus",
                "start_time": "19:00",
                "end_time": "21:00",
                "days": ["mon", "wed"],
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TimeAvailabilityBlock.objects.count(), before + 1)
        block = TimeAvailabilityBlock.objects.get(name="Evening focus")
        self.assertTrue(block.day_monday)
        self.assertTrue(block.day_wednesday)
        response = self.client.post(
            reverse("settings-availability-delete", args=[block.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TimeAvailabilityBlock.objects.filter(pk=block.pk).exists())

    def test_edit_availability_block(self):
        block = TimeAvailabilityBlock.objects.first()
        self.assertIsNotNone(block)
        response = self.client.get(
            reverse("settings-availability-edit", args=[block.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit block")
        self.assertContains(response, f'value="{block.name}"')

        response = self.client.post(
            reverse("settings-availability-update", args=[block.pk]),
            {
                "name": "Updated window",
                "start_time": "08:00",
                "end_time": "12:00",
                "days": ["tue", "thu"],
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        block.refresh_from_db()
        self.assertEqual(block.name, "Updated window")
        self.assertEqual(block.start_time.strftime("%H:%M"), "08:00")
        self.assertEqual(block.end_time.strftime("%H:%M"), "12:00")
        self.assertFalse(block.day_monday)
        self.assertTrue(block.day_tuesday)
        self.assertContains(response, "Updated availability block")

    @patch("lifeos_app.services.notify.deliver_webhook")
    def test_webhook_test(self, mock_deliver):
        save_notification_settings(
            notifications_enabled=True,
            notification_channel="ntfy",
            notification_webhook_url="https://ntfy.example.com/lifeos",
            notification_webhook_token="tok",
            reminder_lead_minutes=15,
        )
        response = self.client.post(reverse("settings-webhook-test"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        mock_deliver.assert_called_once()
        self.assertContains(response, "Test ntfy webhook delivered")
