# ==============================================================================
# File: lifeos_app/tests/test_p5_reminders.py
# Description: P5-05 ETA reminder planning on due/allocation create
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-11
# Last Update: 2026-07-11
# ==============================================================================
"""ReminderDispatch planning — due leads, allocation start, re-arm, eligibility."""

from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from lifeos_app.models import (
    AppSettings,
    ExecutionItem,
    ReminderDispatch,
    ScheduledAllocation,
    SystemEnums,
)
from lifeos_app.services.patch import patch_item_field
from lifeos_app.services.reminders import (
    item_eligible_for_reminders,
    lead_minutes_list,
    plan_allocation_reminders,
    plan_due_reminders,
)


class ReminderPlanningTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.solo = AppSettings.get_solo()
        self.solo.reminder_lead_minutes = 15
        self.solo.reminder_second_lead_minutes = 60
        self.solo.reminder_min_priority = SystemEnums.PriorityLevel.NORMAL
        self.solo.save(
            update_fields=[
                "reminder_lead_minutes",
                "reminder_second_lead_minutes",
                "reminder_min_priority",
            ]
        )

    def test_lead_minutes_unique_sorted(self):
        self.assertEqual(lead_minutes_list(self.solo), [60, 15])

    def test_plan_due_creates_approaching_and_overdue(self):
        due = timezone.now() + timedelta(hours=3)
        item = ExecutionItem.objects.create(
            title="Due soon task",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.HIGH,
            due_at=due,
        )
        result = plan_due_reminders(item, enqueue_eta=False)
        self.assertGreaterEqual(result.created, 2)
        kinds = set(
            ReminderDispatch.objects.filter(execution_item=item).values_list("kind", flat=True)
        )
        self.assertIn(SystemEnums.ReminderKind.DUE_APPROACHING, kinds)
        self.assertIn(SystemEnums.ReminderKind.OVERDUE, kinds)
        approaching = ReminderDispatch.objects.filter(
            execution_item=item,
            kind=SystemEnums.ReminderKind.DUE_APPROACHING,
        )
        self.assertEqual(approaching.count(), 2)  # 60m + 15m leads

    def test_rearm_cancels_old_pending(self):
        due = timezone.now() + timedelta(hours=5)
        item = ExecutionItem.objects.create(
            title="Move due",
            status=SystemEnums.ItemStatus.PLANNED,
            due_at=due,
        )
        plan_due_reminders(item, enqueue_eta=False)
        first_keys = set(
            ReminderDispatch.objects.filter(
                execution_item=item,
                status=SystemEnums.ReminderDispatchStatus.PENDING,
            ).values_list("dedupe_key", flat=True)
        )
        item.due_at = due + timedelta(days=1)
        item.save(update_fields=["due_at"])
        plan_due_reminders(item, enqueue_eta=False)
        cancelled = ReminderDispatch.objects.filter(
            execution_item=item,
            status=SystemEnums.ReminderDispatchStatus.CANCELLED,
        ).count()
        self.assertGreaterEqual(cancelled, 1)
        pending = ReminderDispatch.objects.filter(
            execution_item=item,
            status=SystemEnums.ReminderDispatchStatus.PENDING,
        )
        self.assertTrue(pending.exists())
        self.assertFalse(first_keys & set(pending.values_list("dedupe_key", flat=True)))

    def test_low_priority_skipped(self):
        item = ExecutionItem.objects.create(
            title="Low pri",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.LOW,
            due_at=timezone.now() + timedelta(hours=2),
        )
        self.assertFalse(item_eligible_for_reminders(item, self.solo))
        result = plan_due_reminders(item, enqueue_eta=False)
        self.assertEqual(result.created, 0)

    def test_allocation_start_reminders(self):
        item = ExecutionItem.objects.create(
            title="Block",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.NORMAL,
        )
        start = timezone.now() + timedelta(hours=2)
        alloc = ScheduledAllocation.objects.create(
            execution_item=item,
            start_at=start,
            end_at=start + timedelta(hours=1),
            source=SystemEnums.AllocationSource.SOLVER,
        )
        result = plan_allocation_reminders(alloc, enqueue_eta=False)
        self.assertGreaterEqual(result.created, 1)
        rows = ReminderDispatch.objects.filter(
            scheduled_allocation=alloc,
            kind=SystemEnums.ReminderKind.ALLOCATION_START,
        )
        self.assertEqual(rows.count(), 2)  # 60m + 15m leads
        self.assertTrue(all(r.fire_at <= start for r in rows))

    def test_capture_commit_hook_plans_when_due_set(self):
        """Capture path calls rearm when due_at is present (set via create defaults)."""
        from lifeos_app.services.capture import CapturePreview
        from lifeos_app.services.cmd import commit_capture

        due = timezone.now() + timedelta(hours=5)
        preview = CapturePreview(
            raw="Ship it p2",
            title="Ship it",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.HIGH,
            due_at=due,
        )
        result = commit_capture(preview)
        self.assertTrue(result.ok)
        item = ExecutionItem.objects.get(pk=result.item_id)
        self.assertIsNotNone(item.due_at)
        self.assertTrue(
            ReminderDispatch.objects.filter(
                execution_item=item,
                kind=SystemEnums.ReminderKind.DUE_APPROACHING,
            ).exists()
        )

    @patch("lifeos_app.tasks.fire_reminder_task.apply_async")
    def test_eta_enqueue_when_not_eager(self, mock_async):
        from django.test import override_settings

        due = timezone.now() + timedelta(hours=4)
        item = ExecutionItem.objects.create(
            title="ETA",
            status=SystemEnums.ItemStatus.PLANNED,
            due_at=due,
        )
        with override_settings(CELERY_TASK_ALWAYS_EAGER=False):
            result = plan_due_reminders(item, enqueue_eta=True)
        self.assertGreaterEqual(result.enqueued, 1)
        self.assertTrue(mock_async.called)

    def test_plan_safety_net_creates_missing_due_rows(self):
        due = timezone.now() + timedelta(hours=2)
        item = ExecutionItem.objects.create(
            title="Safety net due",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.HIGH,
            due_at=due,
        )
        from lifeos_app.services.reminders import plan_safety_net

        result = plan_safety_net(horizon_hours=48)
        self.assertGreaterEqual(result.created, 1)
        self.assertTrue(
            ReminderDispatch.objects.filter(
                execution_item=item,
                kind=SystemEnums.ReminderKind.DUE_APPROACHING,
                status=SystemEnums.ReminderDispatchStatus.PENDING,
            ).exists()
        )

    @patch("lifeos_app.services.notify.deliver_webhook")
    def test_fire_single_dispatch_delivers_when_due(self, mock_deliver):
        from lifeos_app.services.reminders import fire_single_dispatch

        self.solo.notifications_enabled = True
        self.solo.notification_webhook_url = "https://ntfy.example/lifeos"
        self.solo.quiet_hours_start = None
        self.solo.quiet_hours_end = None
        self.solo.save(
            update_fields=[
                "notifications_enabled",
                "notification_webhook_url",
                "quiet_hours_start",
                "quiet_hours_end",
            ]
        )
        item = ExecutionItem.objects.create(
            title="Fire me",
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.HIGH,
        )
        dispatch = ReminderDispatch.objects.create(
            execution_item=item,
            kind=SystemEnums.ReminderKind.DUE_APPROACHING,
            status=SystemEnums.ReminderDispatchStatus.PENDING,
            fire_at=timezone.now() - timedelta(minutes=1),
            dedupe_key=f"test-fire-{item.pk}",
        )
        payload = fire_single_dispatch(dispatch.pk)
        self.assertTrue(payload.get("ok"))
        dispatch.refresh_from_db()
        self.assertEqual(dispatch.status, SystemEnums.ReminderDispatchStatus.SENT)
        self.assertTrue(mock_deliver.called)

    def test_fire_single_dispatch_skips_not_due(self):
        from lifeos_app.services.reminders import fire_single_dispatch

        item = ExecutionItem.objects.create(
            title="Later",
            status=SystemEnums.ItemStatus.PLANNED,
        )
        dispatch = ReminderDispatch.objects.create(
            execution_item=item,
            kind=SystemEnums.ReminderKind.DUE_APPROACHING,
            status=SystemEnums.ReminderDispatchStatus.PENDING,
            fire_at=timezone.now() + timedelta(hours=2),
            dedupe_key=f"test-later-{item.pk}",
        )
        payload = fire_single_dispatch(dispatch.pk)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("reason"), "not_due")
