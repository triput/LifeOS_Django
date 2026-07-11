# ==============================================================================
# File: lifeos_app/tests/test_bl_time_004.py
# Description: BL-TIME-004 manual add time on item/container drawers
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Manual time add — extra_actual_seconds without FocusSession rows."""

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import ExecutionItem, FocusSession, WorkspaceContainer
from lifeos_app.services.manual_time import (
    add_time_to_container,
    add_time_to_item,
    container_spent_breakdown,
    item_spent_breakdown,
)


class ManualTimeServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.item = ExecutionItem.objects.filter(is_deleted=False).first()
        self.container = WorkspaceContainer.objects.filter(slug="lifeos-v2").first()

    def test_add_time_to_item(self):
        before = self.item.extra_actual_seconds
        sessions_before = FocusSession.objects.count()
        result = add_time_to_item(self.item, "45m", note="Errand")
        self.assertTrue(result.ok)
        self.assertEqual(result.added_seconds, 45 * 60)
        self.item.refresh_from_db()
        self.assertEqual(self.item.extra_actual_seconds, before + 45 * 60)
        self.assertIn("45m", self.item.notes)
        self.assertIn("Errand", self.item.notes)
        self.assertEqual(FocusSession.objects.count(), sessions_before)

    def test_add_time_rejects_bad_duration(self):
        result = add_time_to_item(self.item, "nope")
        self.assertFalse(result.ok)

    def test_add_time_to_container(self):
        before = self.container.extra_actual_seconds
        result = add_time_to_container(self.container, "1h 30m", note="Offline")
        self.assertTrue(result.ok)
        self.container.refresh_from_db()
        self.assertEqual(self.container.extra_actual_seconds, before + 90 * 60)

    def test_breakdowns(self):
        self.item.time_spent_seconds = 600
        self.item.extra_actual_seconds = 120
        self.item.save(update_fields=["time_spent_seconds", "extra_actual_seconds"])
        spent = item_spent_breakdown(self.item)
        self.assertEqual(spent.total_seconds, 720)
        self.assertEqual(spent.timer_label, "10m")

        self.container.extra_actual_seconds = 300
        self.container.save(update_fields=["extra_actual_seconds"])
        c_spent = container_spent_breakdown(self.container)
        self.assertGreaterEqual(c_spent.own_extra_seconds, 300)
        self.assertGreaterEqual(c_spent.total_seconds, 300)


class ManualTimeDrawerTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")
        self.item = ExecutionItem.objects.filter(title__icontains="cockpit shell").first()
        self.container = WorkspaceContainer.objects.get(slug="lifeos-v2")

    def test_item_drawer_shows_add_time(self):
        response = self.client.get(reverse("drawer-item", args=[self.item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add time")
        self.assertContains(response, f"/items/{self.item.pk}/add-time/")

    def test_item_add_time_post(self):
        before = self.item.extra_actual_seconds
        response = self.client.post(
            reverse("item-add-time", args=[self.item.pk]),
            {"duration": "30m", "note": "Hallway chat"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Added")
        self.item.refresh_from_db()
        self.assertEqual(self.item.extra_actual_seconds, before + 1800)

    def test_container_add_time_post(self):
        before = self.container.extra_actual_seconds
        response = self.client.post(
            reverse("container-add-time", args=[self.container.pk]),
            {"duration": "1h", "note": "Planning"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.container.refresh_from_db()
        self.assertEqual(self.container.extra_actual_seconds, before + 3600)
