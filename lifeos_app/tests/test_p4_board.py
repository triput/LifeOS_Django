# ==============================================================================
# File: lifeos_app/tests/test_p4_board.py
# Description: P4-SURF-BOARD Kanban + stack-rank tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Boards — status columns, dep-locked complete, reorder stack_rank."""

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import ExecutionItem, ItemDependencyLink, SystemEnums
from lifeos_app.services.board import (
    BoardFacets,
    build_board_page,
    move_item_status,
    reorder_items,
)


class BoardServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_status_columns_built(self):
        ctx = build_board_page(BoardFacets(mode="status", show_completed=True))
        self.assertEqual(ctx["board_mode"], "status")
        self.assertTrue(ctx["columns"])
        statuses = [c.status for c in ctx["columns"]]
        self.assertIn(SystemEnums.ItemStatus.BACKLOG, statuses)
        self.assertIn(SystemEnums.ItemStatus.COMPLETED, statuses)

    def test_stack_mode(self):
        ctx = build_board_page(BoardFacets(mode="stack"))
        self.assertEqual(ctx["board_mode"], "stack")
        self.assertTrue(isinstance(ctx["stack_items"], list))

    def test_reorder_items(self):
        items = list(
            ExecutionItem.objects.filter(is_deleted=False, parent_item__isnull=True)[:3]
        )
        self.assertGreaterEqual(len(items), 2)
        ids = [items[1].pk, items[0].pk] + [i.pk for i in items[2:]]
        result = reorder_items(ids)
        self.assertTrue(result.ok)
        items[1].refresh_from_db()
        items[0].refresh_from_db()
        self.assertEqual(items[1].stack_rank, 0)
        self.assertEqual(items[0].stack_rank, 1)

    def test_move_blocked_to_completed_rejected(self):
        dep = ItemDependencyLink.objects.filter(
            link_type=SystemEnums.DependencyLinkType.BLOCKS
        ).select_related("from_item", "to_item").first()
        if dep is None:
            self.skipTest("No BLOCKS dependency in seed")
        blocked = dep.from_item
        prereq = dep.to_item
        if prereq.status == SystemEnums.ItemStatus.COMPLETED:
            prereq.status = SystemEnums.ItemStatus.BACKLOG
            prereq.save(update_fields=["status"])
        result = move_item_status(blocked.pk, SystemEnums.ItemStatus.COMPLETED)
        self.assertFalse(result.ok)


class BoardSurfaceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_board_renders_kanban(self):
        response = self.client.get(reverse("canvas-board"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Boards")
        self.assertContains(response, "board-kanban")
        self.assertContains(response, "Status Kanban")

    def test_board_stack_mode_renders(self):
        response = self.client.get(reverse("canvas-board"), {"mode": "stack"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "board-stack-list")
        self.assertContains(response, "Stack-rank")

    def test_board_move_endpoint(self):
        item = (
            ExecutionItem.objects.filter(is_deleted=False, parent_item__isnull=True)
            .exclude(status=SystemEnums.ItemStatus.COMPLETED)
            .first()
        )
        self.assertIsNotNone(item)
        response = self.client.post(
            reverse("board-move"),
            {
                "item_id": item.pk,
                "status": SystemEnums.ItemStatus.PLANNED,
                "ordered_ids": [item.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        item.refresh_from_db()
        self.assertEqual(item.status, SystemEnums.ItemStatus.PLANNED)

    def test_board_reorder_endpoint(self):
        items = list(
            ExecutionItem.objects.filter(is_deleted=False, parent_item__isnull=True)[:2]
        )
        response = self.client.post(
            reverse("board-reorder"),
            {"ordered_ids": [items[1].pk, items[0].pk]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
