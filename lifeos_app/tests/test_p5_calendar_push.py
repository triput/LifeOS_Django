# ==============================================================================
# File: lifeos_app/tests/test_p5_calendar_push.py
# Description: P5-03 feature-flagged Google Calendar allocation push tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Two-way Google push — flag gate, write-scope gate, insert/patch, pull skip."""

from datetime import timedelta
from unittest.mock import MagicMock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from lifeos_app.models import (
    AppSettings,
    CalendarIntegration,
    ExecutionItem,
    ScheduledAllocation,
    SyncedCalendar,
    SystemEnums,
)
from lifeos_app.services.calendar_push import (
    push_allocation,
    push_pending_allocations,
)
from lifeos_app.services.calendar_sync import (
    CALENDAR_FULL_SCOPE,
    CALENDAR_READONLY_SCOPE,
    LIFEOS_ALLOCATION_PROP,
    google_oauth_scopes,
    parse_google_event,
)
from lifeos_app.services.settings_surface import save_calendar_push_settings


class _FakeEvents:
    def __init__(self):
        self.insert_calls = []
        self.patch_calls = []

    def insert(self, **kwargs):
        self.insert_calls.append(kwargs)
        return MagicMock(execute=MagicMock(return_value={"id": "evt-new-1"}))

    def patch(self, **kwargs):
        self.patch_calls.append(kwargs)
        return MagicMock(execute=MagicMock(return_value={"id": kwargs["eventId"]}))


class _FakeService:
    def __init__(self):
        self._events = _FakeEvents()

    def events(self):
        return self._events


class CalendarPushTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.solo = AppSettings.get_solo()
        self.solo.calendar_push_enabled = True
        self.solo.save(update_fields=["calendar_push_enabled"])

        self.integration = CalendarIntegration.objects.create(
            provider=SystemEnums.CalendarProvider.GOOGLE,
            user_email="owner@example.com",
            credentials_json={
                "token": "tok",
                "refresh_token": "ref",
                "scopes": [CALENDAR_FULL_SCOPE],
            },
            sync_enabled=True,
        )
        self.cal = SyncedCalendar.objects.create(
            integration=self.integration,
            calendar_id="primary",
            summary="Primary",
            is_primary=True,
            sync_enabled=True,
        )
        self.item = ExecutionItem.objects.create(
            title="Deep work block",
            status=SystemEnums.ItemStatus.PLANNED,
            estimated_minutes=60,
        )
        now = timezone.now()
        self.alloc = ScheduledAllocation.objects.create(
            execution_item=self.item,
            start_at=now + timedelta(hours=1),
            end_at=now + timedelta(hours=2),
            source=SystemEnums.AllocationSource.SOLVER,
        )

    def test_scopes_follow_flag(self):
        self.solo.calendar_push_enabled = False
        self.solo.save(update_fields=["calendar_push_enabled"])
        self.assertEqual(google_oauth_scopes(), [CALENDAR_READONLY_SCOPE])
        self.solo.calendar_push_enabled = True
        self.solo.save(update_fields=["calendar_push_enabled"])
        self.assertEqual(google_oauth_scopes(), [CALENDAR_FULL_SCOPE])

    def test_flag_off_skips_api(self):
        self.solo.calendar_push_enabled = False
        self.solo.save(update_fields=["calendar_push_enabled"])
        svc = _FakeService()
        result = push_allocation(self.alloc, service=svc)
        self.assertTrue(result.ok)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(svc._events.insert_calls, [])

    def test_readonly_token_refuses_push(self):
        self.integration.credentials_json = {
            "token": "tok",
            "refresh_token": "ref",
            "scopes": [CALENDAR_READONLY_SCOPE],
        }
        self.integration.save(update_fields=["credentials_json"])
        svc = _FakeService()
        result = push_allocation(self.alloc, service=svc)
        self.assertFalse(result.ok)
        self.assertIn("Reconnect", result.message)
        self.assertEqual(svc._events.insert_calls, [])

    def test_insert_persists_external_id(self):
        svc = _FakeService()
        result = push_allocation(self.alloc, service=svc, push_calendar=self.cal)
        self.assertTrue(result.ok)
        self.assertEqual(result.pushed, 1)
        self.alloc.refresh_from_db()
        self.assertEqual(self.alloc.external_event_id, "evt-new-1")
        self.assertEqual(self.alloc.push_calendar_id, self.cal.pk)
        self.assertEqual(len(svc._events.insert_calls), 1)
        body = svc._events.insert_calls[0]["body"]
        self.assertEqual(
            body["extendedProperties"]["private"][LIFEOS_ALLOCATION_PROP],
            str(self.alloc.pk),
        )

    def test_patch_when_external_id_exists(self):
        self.alloc.external_event_id = "evt-existing"
        self.alloc.push_calendar = self.cal
        self.alloc.save(update_fields=["external_event_id", "push_calendar"])
        svc = _FakeService()
        result = push_allocation(self.alloc, service=svc, push_calendar=self.cal)
        self.assertTrue(result.ok)
        self.assertEqual(result.updated, 1)
        self.assertEqual(len(svc._events.patch_calls), 1)
        self.assertEqual(svc._events.patch_calls[0]["eventId"], "evt-existing")

    def test_parse_skips_lifeos_pushed_events(self):
        raw = {
            "id": "evt-lifeos",
            "summary": "Deep work block",
            "start": {"dateTime": "2026-07-11T10:00:00+00:00"},
            "end": {"dateTime": "2026-07-11T11:00:00+00:00"},
            "extendedProperties": {
                "private": {LIFEOS_ALLOCATION_PROP: "99"},
            },
        }
        self.assertIsNone(parse_google_event(raw))

    def test_save_push_settings(self):
        result = save_calendar_push_settings(enabled=True)
        self.assertTrue(result.ok)
        self.assertIn("reconnect", result.message.lower())
        self.assertTrue(AppSettings.get_solo().calendar_push_enabled)

    def test_push_pending_batch(self):
        ScheduledAllocation.objects.exclude(pk=self.alloc.pk).delete()
        svc = _FakeService()
        result = push_pending_allocations(service_factory=lambda _i: svc)
        self.assertTrue(result.ok)
        self.assertEqual(result.pushed, 1)
        self.alloc.refresh_from_db()
        self.assertEqual(self.alloc.external_event_id, "evt-new-1")
