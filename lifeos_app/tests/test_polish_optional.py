# ==============================================================================
# File: lifeos_app/tests/test_polish_optional.py
# Description: Optional polish — ANAL/CAL/TIME/DRAWER backlog items
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-11
# Last Update: 2026-07-11
# ==============================================================================
"""Regression coverage for post-P5 optional polish."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from zoneinfo import ZoneInfo

from lifeos_app.models import (
    CalendarEvent,
    CalendarIntegration,
    ExecutionItem,
    SyncedCalendar,
    SystemEnums,
    WorkspaceContainer,
)
from lifeos_app.services.calendar_sync import (
    parse_google_event,
    set_calendar_color,
    upsert_parsed_events,
)
from lifeos_app.services.capture import parse_capture
from lifeos_app.services.microsoft_calendar_sync import parse_microsoft_event
from lifeos_app.services.patch import patch_container_field, patch_item_field


class AnalyticsHelpTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        user = get_user_model().objects.get(username="owner")
        self.client.force_login(user)

    def test_avg_score_help_on_analytics(self):
        response = self.client.get(reverse("canvas-analytics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What is this?")
        self.assertContains(response, "System Stability Index")
        # DEF-P55-001 — never render Gold Master / file-path headers in HTML
        self.assertNotContains(response, "Gold Master")
        self.assertNotContains(response, "stability_score_help")


class CalendarColorAndDescriptionTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.integration = CalendarIntegration.objects.create(
            provider=SystemEnums.CalendarProvider.GOOGLE,
            user_email="cal@example.com",
            sync_enabled=True,
            credentials_json={"token": "x", "refresh_token": "y"},
        )
        self.cal = SyncedCalendar.objects.create(
            integration=self.integration,
            calendar_id="primary",
            summary="Personal",
            color="#8294AB",
            sync_enabled=True,
        )

    def test_set_calendar_color_locks(self):
        set_calendar_color(self.cal, color="#ff5500")
        self.cal.refresh_from_db()
        self.assertEqual(self.cal.color.lower(), "#ff5500")
        self.assertTrue(self.cal.color_locked)

    def test_refresh_preserves_locked_color(self):
        set_calendar_color(self.cal, color="#112233")
        existing = SyncedCalendar.objects.get(pk=self.cal.pk)
        self.assertTrue(existing.color_locked)
        defaults = {"summary": "Personal", "is_primary": True, "sync_enabled": True}
        if not existing.color_locked:
            defaults["color"] = "#ffffff"
        SyncedCalendar.objects.update_or_create(
            integration=self.integration,
            calendar_id="primary",
            defaults=defaults,
        )
        existing.refresh_from_db()
        self.assertEqual(existing.color.lower(), "#112233")

    def test_google_description_parsed_and_upserted(self):
        raw = {
            "id": "evt-desc",
            "summary": "Kickoff",
            "description": "Bring slides\nZoom: https://example.com",
            "start": {"dateTime": "2026-07-11T10:00:00-07:00"},
            "end": {"dateTime": "2026-07-11T11:00:00-07:00"},
        }
        parsed = parse_google_event(raw, ZoneInfo("America/Phoenix"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertIn("Bring slides", parsed.description)
        upsert_parsed_events(self.integration, [parsed], source_calendar=self.cal)
        event = CalendarEvent.objects.get(external_id="evt-desc")
        self.assertIn("Zoom", event.description)

    def test_microsoft_body_preview(self):
        raw = {
            "id": "ms-1",
            "subject": "Sync",
            "bodyPreview": "Agenda items",
            "body": {"content": "<p>Ignored when preview present</p>"},
            "start": {"dateTime": "2026-07-11T15:00:00.0000000"},
            "end": {"dateTime": "2026-07-11T16:00:00.0000000"},
            "isAllDay": False,
            "showAs": "busy",
        }
        parsed = parse_microsoft_event(raw, ZoneInfo("UTC"))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.description, "Agenda items")


class HumanTimeAndNotesTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_patch_estimate_human_duration(self):
        item = ExecutionItem.objects.create(
            title="Estimate me",
            status=SystemEnums.ItemStatus.PLANNED,
            estimated_minutes=30,
        )
        result = patch_item_field(item, "estimated_minutes", "1h 30m")
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.estimated_minutes, 90)

    def test_capture_estimate_token(self):
        preview = parse_capture("Ship docs ~2h p2", tz_name="UTC")
        self.assertEqual(preview.title, "Ship docs")
        self.assertEqual(preview.estimated_minutes, 120)

    def test_container_notes_patch(self):
        container = WorkspaceContainer.objects.filter(is_archived=False).first()
        self.assertIsNotNone(container)
        assert container is not None
        result = patch_container_field(container, "notes", "Why this epic exists")
        self.assertTrue(result.ok)
        container.refresh_from_db()
        self.assertEqual(container.notes, "Why this epic exists")

    def test_drawer_shows_container_notes(self):
        container = WorkspaceContainer.objects.filter(is_archived=False).first()
        assert container is not None
        user = get_user_model().objects.get(username="owner")
        client = Client()
        client.force_login(user)
        response = client.get(reverse("drawer-container", args=[container.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notes")
        self.assertContains(response, f"drawer-container-notes-{container.pk}")
