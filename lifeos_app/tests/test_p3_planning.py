# ==============================================================================
# File: lifeos_app/tests/test_p3_planning.py
# Description: P3 tests — Plan Today, scheduler, planner, durations, reminders
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Automated coverage for LifeOS V2 P3 Time & Planning (core slice)."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import (
    ExecutionItem,
    ItemContainerLink,
    ScheduledAllocation,
    SystemEnums,
    WorkspaceContainer,
)
from lifeos_app.services.cmd import commit_command, preview_command
from lifeos_app.services.notify import pending_alert_count, sweep_reminders
from lifeos_app.services.scheduler import run_scheduler, schedulable_candidates
from lifeos_app.services.time_format import (
    format_duration_minutes,
    format_duration_seconds,
    parse_duration_minutes,
)
from lifeos_app.services.today import clear_today, plan_today, today_item_ids


class TimeFormatTests(TestCase):
    def test_format_minutes(self):
        self.assertEqual(format_duration_minutes(90), "1h 30m")
        self.assertEqual(format_duration_minutes(1440), "1d")
        self.assertEqual(format_duration_minutes(45), "45m")

    def test_format_seconds(self):
        self.assertEqual(format_duration_seconds(45), "45s")
        self.assertEqual(format_duration_seconds(90), "1m")
        self.assertEqual(format_duration_seconds(7200), "2h")
        self.assertEqual(format_duration_seconds(0), "0m")

    def test_parse_duration(self):
        self.assertEqual(parse_duration_minutes("2h"), 120)
        self.assertEqual(parse_duration_minutes("1d 4h"), 1680)
        self.assertEqual(parse_duration_minutes("90"), 90)


class PlanTodayTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.today = WorkspaceContainer.objects.get(slug="today")
        self.capture = ExecutionItem.objects.get(title="Wire Cmd+K Lightning Capture")

    def test_plan_today_adds_non_primary_link(self):
        primary = ItemContainerLink.objects.get(item=self.capture, is_primary=True)
        self.assertNotEqual(primary.container, self.today)
        before = today_item_ids()
        result = plan_today(item_ids=[self.capture.pk])
        self.assertTrue(result.ok)
        self.assertIn(self.capture.pk, today_item_ids())
        primary.refresh_from_db()
        self.assertTrue(primary.is_primary)

    def test_clear_today_removes_links(self):
        plan_today(item_ids=[self.capture.pk])
        result = clear_today()
        self.assertTrue(result.ok)
        self.assertNotIn(self.capture.pk, today_item_ids())

    def test_cmd_plan_today_preview(self):
        preview = preview_command("plan today capture")
        self.assertEqual(preview.mode, "do")
        self.assertIn("Plan today", preview.summary)

    def test_cmd_plan_today_commit(self):
        result = commit_command("plan today capture")
        self.assertTrue(result.ok)
        self.assertIn(self.capture.pk, today_item_ids())


class SchedulerTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.focus = ExecutionItem.objects.get(
            title="Implement Focus Engine start/pause/complete"
        )
        ScheduledAllocation.objects.filter(execution_item=self.focus).delete()

    def test_blocked_item_excluded_from_candidates(self):
        self.assertNotIn(self.focus, list(schedulable_candidates()))

    def test_run_scheduler_places_items(self):
        before = ScheduledAllocation.objects.count()
        result = run_scheduler()
        self.assertTrue(result.ok)
        self.assertGreaterEqual(ScheduledAllocation.objects.count(), before)
        self.assertGreater(result.placed, 0)


class PlannerSurfaceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_plan_view_loads(self):
        response = self.client.get(reverse("canvas-plan"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Planner")
        self.assertContains(response, "#today")

    def test_schedule_run_htmx(self):
        response = self.client.post(
            reverse("schedule-run"),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scheduled")

    def test_alerts_glyph(self):
        response = self.client.get(reverse("alerts-glyph"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)


class ReminderSweepTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")

    def test_pending_alert_count(self):
        self.assertGreaterEqual(pending_alert_count(), 1)

    def test_sweep_without_webhook_skips(self):
        result = sweep_reminders()
        self.assertGreaterEqual(result.examined, 1)
        self.assertGreaterEqual(result.skipped + result.sent + result.failed, 1)
