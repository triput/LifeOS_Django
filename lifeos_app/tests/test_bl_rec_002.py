# ==============================================================================
# File: lifeos_app/tests/test_bl_rec_002.py
# Description: BL-REC-002 NL recurrence ending / until <date> tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Recurrence end bound — no spawn after series end day."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from lifeos_app.models import ExecutionItem, RecurrenceRule, SystemEnums
from lifeos_app.services.cmd import commit_command, preview_command
from lifeos_app.services.recurrence import (
    advance_recurrence_on_complete,
    extract_recurrence,
)


class RecurrenceEndDateTests(TestCase):
    def test_extract_until_wednesday(self):
        remainder, preview = extract_recurrence(
            "Study group planning every Wednesday until September 30 2026",
            tz_name="UTC",
        )
        self.assertEqual(remainder, "Study group planning")
        self.assertIsNotNone(preview)
        self.assertFalse(preview.ambiguous)
        self.assertEqual(preview.freq, "WEEKLY")
        self.assertEqual(preview.byweekday, "WE")
        self.assertIsNotNone(preview.ends_at)
        self.assertEqual(preview.ends_at.date(), date(2026, 9, 30))

    def test_oliver_start_and_end(self):
        # Jul 22 2026 = Wed; Aug 13 2026 = Thu.
        remainder, preview = extract_recurrence(
            'Rehearsal for "Oliver!" every Tues, Weds, Thurs, Sat '
            "starting July 22 2026, ending August 13 2026",
            tz_name="UTC",
        )
        self.assertIn("Oliver", remainder)
        self.assertNotIn("every", remainder.lower())
        self.assertNotIn("starting", remainder.lower())
        self.assertNotIn("ending", remainder.lower())
        self.assertFalse(preview.ambiguous)
        self.assertEqual(preview.byweekday, "TU,WE,TH,SA")
        self.assertEqual(preview.starts_at.date(), date(2026, 7, 22))
        self.assertEqual(preview.ends_at.date(), date(2026, 8, 13))
        # Jul 22 2026 is Wednesday — in TU,WE,TH,SA, so first fire is that day.
        self.assertEqual(date(2026, 7, 22).weekday(), 2)
        self.assertEqual(preview.next_occurrence_at.date(), date(2026, 7, 22))

    def test_commit_persists_ends_at(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        result = commit_command(
            "Standup every weekday at 9am until August 1 2026"
        )
        self.assertTrue(result.ok)
        item = ExecutionItem.objects.get(pk=result.item_id)
        rule = RecurrenceRule.objects.get(execution_item=item)
        self.assertIsNotNone(rule.ends_at)
        self.assertEqual(rule.ends_at.date(), date(2026, 8, 1))

    def test_advance_stops_past_end(self):
        ends = datetime(2026, 8, 13, 0, 0, tzinfo=ZoneInfo("UTC"))
        item = ExecutionItem.objects.create(
            title="Last rehearsal",
            status=SystemEnums.ItemStatus.COMPLETED,
            due_at=datetime(2026, 8, 13, 19, 0, tzinfo=ZoneInfo("UTC")),
        )
        RecurrenceRule.objects.create(
            execution_item=item,
            rrule_text="every Thurs",
            freq="WEEKLY",
            byweekday="TH",
            byhour=19,
            interval=1,
            next_occurrence_at=item.due_at,
            ends_at=ends,
            active=True,
        )
        nxt = advance_recurrence_on_complete(item)
        self.assertIsNone(nxt)
        rule = RecurrenceRule.objects.get(pk=item.recurrence.pk)
        self.assertFalse(rule.active)
        self.assertEqual(ExecutionItem.objects.filter(title="Last rehearsal").count(), 1)

    def test_advance_spawns_when_next_still_in_window(self):
        ends = datetime(2026, 8, 20, 0, 0, tzinfo=ZoneInfo("UTC"))
        item = ExecutionItem.objects.create(
            title="Mid series",
            status=SystemEnums.ItemStatus.COMPLETED,
            due_at=datetime(2026, 8, 6, 19, 0, tzinfo=ZoneInfo("UTC")),
        )
        RecurrenceRule.objects.create(
            execution_item=item,
            rrule_text="every Thurs",
            freq="WEEKLY",
            byweekday="TH",
            byhour=19,
            interval=1,
            next_occurrence_at=item.due_at,
            ends_at=ends,
            active=True,
        )
        nxt = advance_recurrence_on_complete(item)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.due_at.date(), date(2026, 8, 13))
        self.assertTrue(nxt.recurrence.active)

    def test_first_after_end_is_non_recurring(self):
        remainder, preview = extract_recurrence(
            "Too late every Monday starting September 1 2026 ending August 1 2026",
            tz_name="UTC",
        )
        self.assertTrue(preview.ambiguous)
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        result = commit_command(
            "Too late every Monday starting September 1 2026 ending August 1 2026"
        )
        self.assertTrue(result.ok)
        item = ExecutionItem.objects.get(pk=result.item_id)
        self.assertFalse(RecurrenceRule.objects.filter(execution_item=item).exists())

    def test_preview_mentions_ends(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        preview = preview_command(
            "Task every day at 8am until December 31 2026"
        )
        self.assertIsNotNone(preview.capture.recurrence)
        self.assertIsNotNone(preview.capture.recurrence.ends_at)
