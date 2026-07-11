# ==============================================================================
# File: lifeos_app/tests/test_p5_recurrence.py
# Description: P5-01 NL recurrence capture + advance-on-complete tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""FR-CMD-005 recurrence phrases and FR-DATA-010 spawn-on-complete."""

from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from lifeos_app.models import ExecutionItem, RecurrenceRule, SystemEnums
from lifeos_app.services.capture import parse_capture
from lifeos_app.services.cmd import commit_command, preview_command
from lifeos_app.services.focus import complete_focus
from lifeos_app.services.patch import patch_item_field
from lifeos_app.services.recurrence import (
    advance_recurrence_on_complete,
    compute_next_occurrence,
    extract_recurrence,
)


class RecurrenceParseTests(TestCase):
    def test_every_day_at_time(self):
        remainder, preview = extract_recurrence("Water plants every day at 8am")
        self.assertEqual(remainder, "Water plants")
        self.assertIsNotNone(preview)
        self.assertFalse(preview.ambiguous)
        self.assertEqual(preview.freq, "DAILY")
        self.assertEqual(preview.byhour, 8)
        self.assertIsNotNone(preview.next_occurrence_at)

    def test_every_mon_wed(self):
        remainder, preview = extract_recurrence("Standup every Mon,Wed at 9:30am")
        self.assertEqual(remainder, "Standup")
        self.assertEqual(preview.freq, "WEEKLY")
        self.assertEqual(preview.byweekday, "MO,WE")
        self.assertEqual(preview.byhour, 9)
        self.assertEqual(preview.byminute, 30)

    def test_every_weekday(self):
        _, preview = extract_recurrence("Check mail every weekday")
        self.assertEqual(preview.freq, "WEEKDAY")
        self.assertIn("MO", preview.byweekday)

    def test_ambiguous_every_other(self):
        remainder, preview = extract_recurrence("Run every other day")
        self.assertEqual(remainder, "Run")
        self.assertTrue(preview.ambiguous)

    def test_capture_preview_strips_phrase(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        cap = parse_capture("#home Buy groceries every Sat at 10am @errand", tz_name="UTC")
        self.assertEqual(cap.title, "Buy groceries")
        self.assertIsNotNone(cap.recurrence)
        self.assertEqual(cap.recurrence.byweekday, "SA")
        self.assertIn("errand", cap.tag_slugs)
        self.assertEqual(cap.container_slug, "home")


class RecurrenceCommitAdvanceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_commit_creates_rule(self):
        result = commit_command("Floss every day at 7am")
        self.assertTrue(result.ok)
        item = ExecutionItem.objects.get(pk=result.item_id)
        rule = item.recurrence
        self.assertEqual(rule.freq, "DAILY")
        self.assertEqual(rule.byhour, 7)
        self.assertTrue(rule.active)
        self.assertIsNotNone(item.due_at)

    def test_preview_shows_recurrence(self):
        preview = preview_command("Trash every weekday at 6pm")
        self.assertEqual(preview.mode, "capture")
        self.assertIn("every weekday", preview.summary.lower())
        self.assertIsNotNone(preview.capture.recurrence)

    def test_advance_spawns_next_and_keeps_history(self):
        item = ExecutionItem.objects.create(
            title="Recurring chore",
            status=SystemEnums.ItemStatus.PLANNED,
            due_at=timezone.now() - timedelta(hours=1),
        )
        RecurrenceRule.objects.create(
            execution_item=item,
            rrule_text="every day at 9am",
            freq="DAILY",
            byhour=9,
            interval=1,
            next_occurrence_at=item.due_at,
            active=True,
        )
        item.status = SystemEnums.ItemStatus.COMPLETED
        item.save(update_fields=["status"])

        nxt = advance_recurrence_on_complete(item)
        self.assertIsNotNone(nxt)
        item.refresh_from_db()
        self.assertEqual(item.status, SystemEnums.ItemStatus.COMPLETED)
        self.assertFalse(hasattr(item, "recurrence") and RecurrenceRule.objects.filter(execution_item=item).exists())
        self.assertEqual(nxt.title, "Recurring chore")
        self.assertEqual(nxt.status, SystemEnums.ItemStatus.PLANNED)
        self.assertTrue(nxt.due_at > timezone.now())
        self.assertEqual(nxt.recurrence.freq, "DAILY")

    def test_complete_focus_advances(self):
        result = commit_command("Nightly backup every day at 11pm")
        item = ExecutionItem.objects.get(pk=result.item_id)
        focus_result = complete_focus(item)
        self.assertTrue(focus_result.ok)
        self.assertIn("Next occurrence", focus_result.message)
        item.refresh_from_db()
        self.assertEqual(item.status, SystemEnums.ItemStatus.COMPLETED)
        self.assertEqual(ExecutionItem.objects.filter(title="Nightly backup").count(), 2)

    def test_patch_complete_advances(self):
        result = commit_command("Weekly review every Fri at 4pm")
        item = ExecutionItem.objects.get(pk=result.item_id)
        patch = patch_item_field(item, "status", "COMPLETED")
        self.assertTrue(patch.ok)
        self.assertIn("Next due", patch.message)
        self.assertEqual(ExecutionItem.objects.filter(title="Weekly review").count(), 2)

    def test_compute_weekly_next(self):
        after = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        nxt = compute_next_occurrence(
            freq="WEEKLY",
            byweekday="MO,WE",
            byhour=9,
            byminute=0,
            after=after,
        )
        self.assertGreater(nxt, after)
        self.assertIn(nxt.weekday(), (0, 2))
        self.assertEqual(nxt.hour, 9)
