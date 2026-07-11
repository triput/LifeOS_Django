# ==============================================================================
# File: lifeos_app/tests/test_p3_calendar.py
# Description: P3 calendar pull tests (ENG-CAL)
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Google Calendar sync parsing and upsert (no live API in tests)."""

from datetime import date
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import AppSettings, CalendarEvent, CalendarIntegration, SyncedCalendar
from lifeos_app.services.calendar_config import (
    get_oauth_config,
    oauth_configured,
    validate_oauth_config,
)
from lifeos_app.services.calendar_oauth import start_authorization
from lifeos_app.services.calendar_sync import (
    parse_google_event,
    pull_calendar,
    refresh_synced_calendars,
    upsert_parsed_events,
)
from lifeos_app.services.plan import calendar_is_live


class CalendarConfigTests(TestCase):
    def test_oauth_from_appsettings(self):
        solo = AppSettings.get_solo()
        solo.google_oauth_client_id = "123456789012-abcdef.apps.googleusercontent.com"
        solo.google_oauth_client_secret = "GOCSPX-test-secret-value"
        solo.save()
        cfg = get_oauth_config()
        self.assertEqual(cfg.client_id, "123456789012-abcdef.apps.googleusercontent.com")
        self.assertEqual(cfg.source, "appsettings")
        self.assertTrue(oauth_configured())

    def test_invalid_client_id_rejected(self):
        solo = AppSettings.get_solo()
        solo.google_oauth_client_id = "not-a-real-client-id"
        solo.google_oauth_client_secret = "GOCSPX-test-secret-value"
        solo.save()
        self.assertFalse(oauth_configured())
        errors = validate_oauth_config()
        self.assertTrue(any("apps.googleusercontent.com" in e for e in errors))

    def test_quoted_secret_stripped(self):
        solo = AppSettings.get_solo()
        solo.google_oauth_client_id = "123456789012-abcdef.apps.googleusercontent.com"
        solo.google_oauth_client_secret = '"GOCSPX-quoted-secret"'
        solo.save()
        cfg = get_oauth_config()
        self.assertEqual(cfg.client_secret, "GOCSPX-quoted-secret")
        self.assertTrue(oauth_configured())

    def test_pkce_verifier_captured_on_authorization_start(self):
        solo = AppSettings.get_solo()
        solo.google_oauth_client_id = "123456789012-abcdef.apps.googleusercontent.com"
        solo.google_oauth_client_secret = "GOCSPX-test-secret-value"
        solo.save()
        auth = start_authorization(
            "test-state",
            redirect_uri="http://127.0.0.1:8000/calendar/oauth2callback/",
        )
        self.assertIn("accounts.google.com", auth.url)
        self.assertTrue(len(auth.code_verifier) > 20)

    def test_oauth_not_configured_by_default(self):
        solo = AppSettings.get_solo()
        solo.google_oauth_client_id = ""
        solo.google_oauth_client_secret = ""
        solo.save()
        self.assertFalse(oauth_configured())


class CalendarParseTests(TestCase):
    def test_parse_timed_event(self):
        raw = {
            "id": "evt-1",
            "summary": "Standup",
            "start": {"dateTime": "2026-07-09T14:00:00-07:00"},
            "end": {"dateTime": "2026-07-09T14:30:00-07:00"},
            "transparency": "opaque",
        }
        parsed = parse_google_event(raw, ZoneInfo("America/Phoenix"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.title, "Standup")
        self.assertFalse(parsed.is_all_day)
        self.assertTrue(parsed.is_blocking)

    def test_parse_all_day_free_event(self):
        raw = {
            "id": "evt-2",
            "summary": "Holiday",
            "start": {"date": "2026-07-09"},
            "end": {"date": "2026-07-10"},
            "transparency": "transparent",
        }
        parsed = parse_google_event(raw, ZoneInfo("UTC"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertTrue(parsed.is_all_day)
        self.assertFalse(parsed.is_blocking)


class CalendarPullTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.integration = CalendarIntegration.objects.get(user_email="owner@lifeos.local")
        self.integration.credentials_json = {
            "token": "test",
            "refresh_token": "refresh",
            "client_id": "cid",
            "client_secret": "sec",
        }
        self.integration.save()

    def test_calendar_is_live(self):
        self.assertTrue(calendar_is_live(self.integration))

    def test_pull_upserts_events(self):
        work_cal = SyncedCalendar.objects.create(
            integration=self.integration,
            calendar_id="work@example.com",
            summary="Work",
            sync_enabled=True,
        )
        raw_events = [
            {
                "id": "google-abc",
                "summary": "Dentist",
                "start": {"dateTime": "2026-07-10T10:00:00-07:00"},
                "end": {"dateTime": "2026-07-10T11:00:00-07:00"},
            },
            {
                "id": "google-def",
                "summary": "Focus block",
                "start": {"date": "2026-07-11"},
                "end": {"date": "2026-07-12"},
            },
        ]
        result = pull_calendar(
            integration=self.integration,
            raw_events=raw_events,
            source_calendar=work_cal,
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            CalendarEvent.objects.filter(source_calendar=work_cal, external_id="google-abc").count(),
            1,
        )
        dentist = CalendarEvent.objects.get(source_calendar=work_cal, external_id="google-abc")
        self.assertEqual(dentist.title, "Dentist")

    def test_refresh_synced_calendars_from_raw_list(self):
        self.integration.credentials_json = {"token": "x", "refresh_token": "y", "client_id": "z"}
        self.integration.save()

        def fake_list(integration):
            return [
                {
                    "id": "personal@gmail.com",
                    "summary": "Personal",
                    "primary": True,
                    "backgroundColor": "#5484ed",
                },
                {
                    "id": "work@company.com",
                    "summary": "Work",
                    "backgroundColor": "#f83a22",
                },
            ]

        from unittest.mock import patch

        with patch(
            "lifeos_app.services.calendar_sync.fetch_google_calendar_list",
            side_effect=fake_list,
        ):
            count = refresh_synced_calendars(self.integration)
        self.assertEqual(count, 2)
        personal = SyncedCalendar.objects.get(calendar_id="personal@gmail.com")
        work = SyncedCalendar.objects.get(calendar_id="work@company.com")
        self.assertTrue(personal.sync_enabled)
        self.assertFalse(work.sync_enabled)
        work.sync_enabled = True
        work.save()
        with patch(
            "lifeos_app.services.calendar_sync.fetch_google_calendar_list",
            side_effect=fake_list,
        ):
            refresh_synced_calendars(self.integration)
        work.refresh_from_db()
        self.assertTrue(work.sync_enabled)

    def test_seed_integration_rejected_for_live_pull(self):
        seed = CalendarIntegration.objects.create(
            user_email="seed-only@lifeos.local",
            credentials_json={"seed": True},
        )
        result = pull_calendar(integration=seed, raw_events=[])
        self.assertFalse(result.ok)


class CalendarViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_calendar_status_partial(self):
        response = self.client.get(reverse("calendar-status"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Google Calendar")
        self.assertContains(response, "Outlook / Microsoft 365")
        self.assertContains(response, "Connect")
        self.assertContains(response, "Settings")

    def test_planner_shows_calendar_panel(self):
        response = self.client.get(reverse("canvas-plan"))
        self.assertContains(response, "plan-calendar-panel")

    def test_calendar_toggle_view(self):
        integration = CalendarIntegration.objects.get(user_email="owner@lifeos.local")
        integration.credentials_json = {"token": "t", "refresh_token": "r"}
        integration.save()
        cal = SyncedCalendar.objects.create(
            integration=integration,
            calendar_id="travel@gmail.com",
            summary="Travel",
            sync_enabled=False,
        )
        response = self.client.post(
            reverse("calendar-toggle", args=[cal.pk]),
            {"sync_enabled": "true"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        cal.refresh_from_db()
        self.assertTrue(cal.sync_enabled)
        self.assertContains(response, "Travel")
