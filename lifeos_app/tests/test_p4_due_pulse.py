# ==============================================================================
# File: lifeos_app/tests/test_p4_due_pulse.py
# Description: P4-NOTIFY-POLISH ambient due/overdue pulse tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Due urgency classification + Matrix/Board data-due attributes."""

from datetime import timedelta
from types import SimpleNamespace

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from lifeos_app.models import AppSettings, ExecutionItem, SystemEnums
from lifeos_app.services.due_pulse import (
    DUE_NONE,
    DUE_OVERDUE,
    DUE_SOON,
    classify_due_urgency,
    soon_window_minutes,
)


class DuePulseServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.now = timezone.now()

    def test_soon_window_uses_wider_lead(self):
        solo = AppSettings.get_solo()
        solo.reminder_lead_minutes = 15
        solo.reminder_second_lead_minutes = 1440
        solo.save()
        self.assertEqual(soon_window_minutes(solo), 1440)

    def test_overdue_and_soon_and_none(self):
        overdue = SimpleNamespace(
            status=SystemEnums.ItemStatus.PLANNED,
            due_at=self.now - timedelta(hours=1),
        )
        soon = SimpleNamespace(
            status=SystemEnums.ItemStatus.PLANNED,
            due_at=self.now + timedelta(hours=2),
        )
        later = SimpleNamespace(
            status=SystemEnums.ItemStatus.PLANNED,
            due_at=self.now + timedelta(days=5),
        )
        done = SimpleNamespace(
            status=SystemEnums.ItemStatus.COMPLETED,
            due_at=self.now - timedelta(hours=1),
        )
        bare = SimpleNamespace(status=SystemEnums.ItemStatus.BACKLOG, due_at=None)

        self.assertEqual(classify_due_urgency(overdue, now=self.now, soon_minutes=1440), DUE_OVERDUE)
        self.assertEqual(classify_due_urgency(soon, now=self.now, soon_minutes=1440), DUE_SOON)
        self.assertEqual(classify_due_urgency(later, now=self.now, soon_minutes=1440), DUE_NONE)
        self.assertEqual(classify_due_urgency(done, now=self.now, soon_minutes=1440), DUE_NONE)
        self.assertEqual(classify_due_urgency(bare, now=self.now, soon_minutes=1440), DUE_NONE)


class DuePulseSurfaceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")
        item = ExecutionItem.objects.filter(due_at__isnull=False).exclude(
            status=SystemEnums.ItemStatus.COMPLETED
        ).first()
        self.assertIsNotNone(item)
        item.due_at = timezone.now() - timedelta(hours=2)
        item.status = SystemEnums.ItemStatus.PLANNED
        item.save(update_fields=["due_at", "status"])
        self.overdue_pk = item.pk

    def test_matrix_marks_overdue(self):
        item = ExecutionItem.objects.get(pk=self.overdue_pk)
        container = item.primary_container()
        self.assertIsNotNone(container)
        response = self.client.get(reverse("matrix-children", args=[container.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="matrix-item-{self.overdue_pk}"')
        self.assertContains(response, 'data-due="overdue"')

    def test_overview_marks_overdue(self):
        response = self.client.get(reverse("canvas-overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-due="overdue"')

    def test_board_marks_overdue(self):
        response = self.client.get(reverse("canvas-board"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-item-id="{self.overdue_pk}"')
        self.assertContains(response, 'data-due="overdue"')
