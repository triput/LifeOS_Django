# ==============================================================================
# File: lifeos_app/tests/test_bl_rec_001.py
# Description: BL-REC-001 NL recurrence starting <date> tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Recurrence start floor — first occurrence on/after starting date."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase

from lifeos_app.models import ExecutionItem, RecurrenceRule
from lifeos_app.services.cmd import commit_command, preview_command
from lifeos_app.services.recurrence import compute_next_occurrence, extract_recurrence


class RecurrenceStartDateTests(TestCase):
    def test_july_20_2026_is_monday(self):
        self.assertEqual(date(2026, 7, 20).weekday(), 0)

    def test_extract_starting_monday(self):
        remainder, preview = extract_recurrence(
            "Buy groceries from Freddy's every Monday at 10AM starting July 20 2026",
            tz_name="UTC",
        )
        self.assertEqual(remainder, "Buy groceries from Freddy's")
        self.assertIsNotNone(preview)
        self.assertFalse(preview.ambiguous)
        self.assertEqual(preview.freq, "WEEKLY")
        self.assertEqual(preview.byweekday, "MO")
        self.assertEqual(preview.byhour, 10)
        self.assertIsNotNone(preview.starts_at)
        self.assertEqual(preview.next_occurrence_at.date(), date(2026, 7, 20))
        self.assertEqual(preview.next_occurrence_at.hour, 10)

    def test_starting_skips_to_next_matching_weekday(self):
        # July 21 2026 is Tuesday — first Monday on/after is July 27.
        self.assertEqual(date(2026, 7, 21).weekday(), 1)
        _, preview = extract_recurrence(
            "Standup every Monday at 9am starting July 21 2026",
            tz_name="UTC",
        )
        self.assertEqual(preview.next_occurrence_at.date(), date(2026, 7, 27))

    def test_compute_not_before(self):
        after = datetime(2026, 7, 10, 12, 0, tzinfo=ZoneInfo("UTC"))
        not_before = datetime(2026, 7, 20, 0, 0, tzinfo=ZoneInfo("UTC"))
        nxt = compute_next_occurrence(
            freq="WEEKLY",
            byweekday="MO",
            byhour=10,
            after=after,
            not_before=not_before,
        )
        self.assertEqual(nxt.date(), date(2026, 7, 20))
        self.assertEqual(nxt.hour, 10)

    def test_commit_persists_starts_at(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        result = commit_command(
            "Freddy groceries every Monday at 10AM starting July 20 2026"
        )
        self.assertTrue(result.ok)
        item = ExecutionItem.objects.get(pk=result.item_id)
        rule = RecurrenceRule.objects.get(execution_item=item)
        self.assertIsNotNone(rule.starts_at)
        self.assertEqual(item.due_at.date(), date(2026, 7, 20))

    def test_preview_mentions_starts(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        preview = preview_command(
            "Task every weekday at 8am starting August 1 2026"
        )
        self.assertIsNotNone(preview.capture)
        self.assertIsNotNone(preview.capture.recurrence)
        self.assertIsNotNone(preview.capture.recurrence.starts_at)
