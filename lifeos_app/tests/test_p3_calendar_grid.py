# ==============================================================================
# File: lifeos_app/tests/test_p3_calendar_grid.py
# Description: BL-CAL-002 unified calendar grid tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Month/week calendar grid — merge, display filters, surface."""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from lifeos_app.models import (
    CalendarEvent,
    CalendarIntegration,
    ExecutionItem,
    ScheduledAllocation,
    SyncedCalendar,
    SystemEnums,
    WorkspaceContainer,
)
from lifeos_app.services.calendar_grid import (
    calendar_grid_context,
    month_grid_span,
    plan_blocks_for_range,
    set_calendar_display_enabled,
    week_start,
)


class CalendarGridServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.today = timezone.localdate()
        self.integration = CalendarIntegration.objects.create(
            provider=SystemEnums.CalendarProvider.GOOGLE,
            user_email="owner@example.com",
            credentials_json={"token": "x", "refresh_token": "y"},
        )
        self.cal = SyncedCalendar.objects.create(
            integration=self.integration,
            calendar_id="primary",
            summary="Personal",
            color="#AABBCC",
            sync_enabled=True,
            display_enabled=True,
        )

    def _aware(self, day, hour, minute=0):
        return timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=hour, minute=minute)))

    def test_week_start_monday(self):
        # 2026-07-10 is Friday
        friday = datetime(2026, 7, 10).date()
        self.assertEqual(week_start(friday).weekday(), 0)
        self.assertEqual(week_start(friday), datetime(2026, 7, 6).date())

    def test_month_grid_span_covers_full_weeks(self):
        start, end = month_grid_span(2026, 7)
        self.assertEqual(start.weekday(), 0)
        self.assertEqual(end.weekday(), 6)
        self.assertLessEqual(start, datetime(2026, 7, 1).date())
        self.assertGreaterEqual(end, datetime(2026, 7, 31).date())

    def test_plan_blocks_merge_allocations_and_events(self):
        container = WorkspaceContainer.objects.filter(slug="inbox").first()
        item = ExecutionItem.objects.create(
            title="Deep work block",
            item_type=SystemEnums.ItemType.TASK,
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.HIGH,
        )
        if container:
            item.container_links.create(container=container, is_primary=True)
        ScheduledAllocation.objects.create(
            execution_item=item,
            start_at=self._aware(self.today, 10),
            end_at=self._aware(self.today, 11),
            source=SystemEnums.AllocationSource.MANUAL,
        )
        CalendarEvent.objects.create(
            integration=self.integration,
            source_calendar=self.cal,
            external_id="evt-1",
            title="Standup",
            start_at=self._aware(self.today, 9),
            end_at=self._aware(self.today, 9, 30),
            is_blocking=True,
        )
        blocks = plan_blocks_for_range(self.today, self.today)
        kinds = {b.kind for b in blocks}
        self.assertIn("allocation", kinds)
        self.assertIn("calendar", kinds)
        titles = {b.title for b in blocks}
        self.assertIn("Deep work block", titles)
        self.assertIn("Standup", titles)

    def test_display_enabled_filters_calendar_events(self):
        CalendarEvent.objects.create(
            integration=self.integration,
            source_calendar=self.cal,
            external_id="evt-2",
            title="Hidden meeting",
            start_at=self._aware(self.today, 14),
            end_at=self._aware(self.today, 15),
            is_blocking=True,
        )
        set_calendar_display_enabled(self.cal, enabled=False)
        blocks = plan_blocks_for_range(
            self.today,
            self.today,
            show_allocations=False,
            calendar_ids=set(
                SyncedCalendar.objects.filter(display_enabled=True).values_list("pk", flat=True)
            ),
        )
        self.assertEqual(blocks, [])

    def test_hide_allocations(self):
        container = WorkspaceContainer.objects.filter(slug="inbox").first()
        item = ExecutionItem.objects.create(
            title="Only allocation",
            item_type=SystemEnums.ItemType.TASK,
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.NORMAL,
        )
        if container:
            item.container_links.create(container=container, is_primary=True)
        ScheduledAllocation.objects.create(
            execution_item=item,
            start_at=self._aware(self.today, 12),
            end_at=self._aware(self.today, 13),
            source=SystemEnums.AllocationSource.SOLVER,
        )
        blocks = plan_blocks_for_range(self.today, self.today, show_allocations=False, calendar_ids=set())
        self.assertEqual(blocks, [])

    def test_calendar_grid_context_month(self):
        ctx = calendar_grid_context(view="month", anchor=datetime(2026, 7, 15).date())
        self.assertEqual(ctx["grid_view"], "month")
        self.assertIn("July", ctx["grid_title"])
        self.assertTrue(ctx["grid_weeks"])
        self.assertEqual(len(ctx["grid_weeks"][0]), 7)


class CalendarGridViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")
        self.integration = CalendarIntegration.objects.create(
            provider=SystemEnums.CalendarProvider.GOOGLE,
            user_email="owner@example.com",
            credentials_json={"token": "x", "refresh_token": "y"},
        )
        self.cal = SyncedCalendar.objects.create(
            integration=self.integration,
            calendar_id="primary",
            summary="Work",
            color="#112233",
            sync_enabled=True,
            display_enabled=True,
        )

    def test_calendar_grid_page_renders(self):
        response = self.client.get(reverse("canvas-plan-calendar"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Calendar")
        self.assertContains(response, "Month")
        self.assertContains(response, "Week")
        self.assertContains(response, "Sources")
        self.assertContains(response, "LifeOS allocations")

    def test_week_view(self):
        response = self.client.get(reverse("canvas-plan-calendar"), {"view": "week"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Week of")

    def test_display_toggle(self):
        response = self.client.post(
            reverse("plan-calendar-display-toggle", args=[self.cal.pk]),
            {"display_enabled": "", "view": "month", "day": timezone.localdate().isoformat()},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.cal.refresh_from_db()
        self.assertFalse(self.cal.display_enabled)

        response = self.client.post(
            reverse("plan-calendar-display-toggle", args=[self.cal.pk]),
            {"display_enabled": "on", "view": "month", "day": timezone.localdate().isoformat()},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.cal.refresh_from_db()
        self.assertTrue(self.cal.display_enabled)

    def test_allocations_toggle(self):
        response = self.client.post(
            reverse("plan-calendar-allocations-toggle"),
            {"view": "month", "day": timezone.localdate().isoformat()},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get("cal_grid_show_allocations"))

    def test_day_planner_links_to_grid(self):
        response = self.client.get(reverse("canvas-plan"))
        self.assertContains(response, reverse("canvas-plan-calendar"))

    def test_grid_allocation_chip_opens_item_drawer(self):
        container = WorkspaceContainer.objects.filter(slug="inbox").first()
        item = ExecutionItem.objects.create(
            title="Clickable alloc",
            item_type=SystemEnums.ItemType.TASK,
            status=SystemEnums.ItemStatus.PLANNED,
            priority=SystemEnums.PriorityLevel.NORMAL,
        )
        if container:
            item.container_links.create(container=container, is_primary=True)
        day = timezone.localdate()
        ScheduledAllocation.objects.create(
            execution_item=item,
            start_at=timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=10))),
            end_at=timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=11))),
            source=SystemEnums.AllocationSource.MANUAL,
        )
        response = self.client.get(
            reverse("canvas-plan-calendar"),
            {"view": "week", "day": day.isoformat()},
        )
        self.assertContains(response, reverse("drawer-item", args=[item.pk]))
        self.assertContains(response, "data-lifeos-drawer")

    def test_grid_calendar_event_chip_opens_event_drawer(self):
        day = timezone.localdate()
        event = CalendarEvent.objects.create(
            integration=self.integration,
            source_calendar=self.cal,
            external_id="click-evt",
            title="External standup",
            start_at=timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=9))),
            end_at=timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=9, minute=30))),
            is_blocking=True,
        )
        response = self.client.get(
            reverse("canvas-plan-calendar"),
            {"view": "week", "day": day.isoformat()},
        )
        self.assertContains(response, reverse("drawer-calendar-event", args=[event.pk]))

    def test_calendar_event_drawer_readonly(self):
        day = timezone.localdate()
        event = CalendarEvent.objects.create(
            integration=self.integration,
            source_calendar=self.cal,
            external_id="detail-evt",
            title="Dentist",
            start_at=timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=15))),
            end_at=timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=16))),
            is_blocking=True,
        )
        response = self.client.get(reverse("drawer-calendar-event", args=[event.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dentist")
        self.assertContains(response, "Read-only")
        self.assertContains(response, "Work")

    def test_timeline_calendar_row_clickable(self):
        day = timezone.localdate()
        event = CalendarEvent.objects.create(
            integration=self.integration,
            source_calendar=self.cal,
            external_id="tl-evt",
            title="Timeline meeting",
            start_at=timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=11))),
            end_at=timezone.make_aware(datetime.combine(day, datetime.min.time().replace(hour=12))),
            is_blocking=True,
        )
        response = self.client.get(reverse("canvas-plan"), {"day": day.isoformat()})
        self.assertContains(response, reverse("drawer-calendar-event", args=[event.pk]))
        self.assertContains(response, "Timeline meeting")
