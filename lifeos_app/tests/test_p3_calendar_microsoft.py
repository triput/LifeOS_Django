# ==============================================================================
# File: lifeos_app/tests/test_p3_calendar_microsoft.py
# Description: Microsoft Graph calendar tests (BL-CAL-001)
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Microsoft calendar sync parsing and config (no live Graph API in tests)."""

from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import AppSettings, CalendarEvent, CalendarIntegration, SyncedCalendar, SystemEnums
from lifeos_app.services.calendar_config import get_oauth_config, oauth_configured
from lifeos_app.services.microsoft_calendar_oauth import start_authorization
from lifeos_app.services.microsoft_calendar_sync import (
    parse_microsoft_event,
    pull_microsoft_calendar,
    refresh_synced_calendars,
)
from lifeos_app.services.plan import calendar_is_live


class MicrosoftCalendarConfigTests(TestCase):
    def test_oauth_from_appsettings(self):
        solo = AppSettings.get_solo()
        solo.microsoft_oauth_client_id = "11111111-2222-3333-4444-555555555555"
        solo.microsoft_oauth_client_secret = "ms-secret-value"
        solo.save()
        cfg = get_oauth_config(provider=SystemEnums.CalendarProvider.MICROSOFT)
        self.assertEqual(cfg.client_id, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(cfg.source, "appsettings")
        redirect = "http://127.0.0.1:8000/calendar/microsoft/oauth2callback/"
        self.assertTrue(oauth_configured(provider=SystemEnums.CalendarProvider.MICROSOFT, redirect_uri=redirect))

    def test_pkce_authorization_url(self):
        solo = AppSettings.get_solo()
        solo.microsoft_oauth_client_id = "11111111-2222-3333-4444-555555555555"
        solo.microsoft_oauth_client_secret = "ms-secret-value"
        solo.save()
        auth = start_authorization(
            "test-state",
            redirect_uri="http://127.0.0.1:8000/calendar/microsoft/oauth2callback/",
        )
        self.assertIn("login.microsoftonline.com", auth.url)
        self.assertIn("code_challenge=", auth.url)
        self.assertTrue(len(auth.code_verifier) > 20)


class MicrosoftCalendarParseTests(TestCase):
    def test_parse_timed_event(self):
        raw = {
            "id": "ms-evt-1",
            "subject": "Team sync",
            "start": {"dateTime": "2026-07-09T14:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-07-09T15:00:00.0000000", "timeZone": "UTC"},
            "isAllDay": False,
            "showAs": "busy",
        }
        parsed = parse_microsoft_event(raw, ZoneInfo("UTC"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.title, "Team sync")
        self.assertTrue(parsed.is_blocking)

    def test_parse_free_all_day_event(self):
        raw = {
            "id": "ms-evt-2",
            "subject": "PTO",
            "start": {"dateTime": "2026-07-09T00:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": "2026-07-10T00:00:00.0000000", "timeZone": "UTC"},
            "isAllDay": True,
            "showAs": "free",
        }
        parsed = parse_microsoft_event(raw, ZoneInfo("UTC"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed.is_all_day)
        self.assertFalse(parsed.is_blocking)


class MicrosoftCalendarPullTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.integration = CalendarIntegration.objects.create(
            provider=SystemEnums.CalendarProvider.MICROSOFT,
            user_email="owner@outlook.com",
            credentials_json={
                "token": "test",
                "refresh_token": "refresh",
                "client_id": "cid",
            },
        )

    def test_calendar_is_live(self):
        self.assertTrue(calendar_is_live(self.integration))

    def test_pull_upserts_events(self):
        work_cal = SyncedCalendar.objects.create(
            integration=self.integration,
            calendar_id="AAMkAGI2TG93AAA=",
            summary="Work",
            sync_enabled=True,
        )
        raw_events = [
            {
                "id": "ms-abc",
                "subject": "Client call",
                "start": {"dateTime": "2026-07-10T10:00:00.0000000", "timeZone": "UTC"},
                "end": {"dateTime": "2026-07-10T11:00:00.0000000", "timeZone": "UTC"},
                "isAllDay": False,
                "showAs": "busy",
            },
        ]
        result = pull_microsoft_calendar(
            self.integration,
            raw_events=raw_events,
            source_calendar=work_cal,
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            CalendarEvent.objects.filter(source_calendar=work_cal, external_id="ms-abc").count(),
            1,
        )

    def test_refresh_synced_calendars_from_raw_list(self):
        def fake_list(integration):
            return [
                {
                    "id": "cal-personal",
                    "name": "Personal",
                    "isDefaultCalendar": True,
                    "hexColor": "#5484ed",
                },
                {
                    "id": "cal-work",
                    "name": "Work",
                    "hexColor": "f83a22",
                },
            ]

        with patch(
            "lifeos_app.services.microsoft_calendar_sync.fetch_microsoft_calendar_list",
            side_effect=fake_list,
        ):
            count = refresh_synced_calendars(self.integration)
        self.assertEqual(count, 2)
        personal = SyncedCalendar.objects.get(calendar_id="cal-personal")
        self.assertTrue(personal.sync_enabled)
        self.assertEqual(personal.color, "#5484ed")


class MicrosoftCalendarViewTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_calendar_status_shows_both_providers(self):
        response = self.client.get(reverse("calendar-status"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Google Calendar")
        self.assertContains(response, "Outlook / Microsoft 365")

    def test_planner_shows_both_calendar_panels(self):
        response = self.client.get(reverse("canvas-plan"))
        self.assertContains(response, "plan-calendar-panel-google")
        self.assertContains(response, "plan-calendar-panel-microsoft")
