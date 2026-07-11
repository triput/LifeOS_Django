# ==============================================================================
# File: lifeos_app/tests/test_p2_matrix.py
# Description: P2 tests — matrix, patch-field, drawer dock, bulk actions
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Automated coverage for LifeOS V2 P2 Matrix & Drawer."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import ExecutionItem, SystemEnums, WorkspaceContainer
from lifeos_app.services.dock import dock_list, dock_minimize
from lifeos_app.services.patch import patch_item_field
from lifeos_app.services.matrix import MatrixFacets, root_containers


class MatrixServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")

    def test_root_containers_returns_epics(self):
        facets = MatrixFacets()
        roots = list(root_containers(facets))
        self.assertTrue(any(c.slug == "lifeos-v2" for c in roots))

    def test_patch_item_priority(self):
        item = ExecutionItem.objects.first()
        result = patch_item_field(item, "priority", "1")
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.priority, SystemEnums.PriorityLevel.CRITICAL)

    def test_patch_complete_blocked_by_dependency(self):
        item = ExecutionItem.objects.get(title="Implement Focus Engine start/pause/complete")
        result = patch_item_field(item, "status", SystemEnums.ItemStatus.COMPLETED)
        self.assertFalse(result.ok)


class DockSessionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser("owner", "o@test", "pass")
        self.client = Client()
        self.client.login(username="owner", password="pass")

    def test_dock_minimize_lru_cap(self):
        from django.test import RequestFactory

        from lifeos_app.services.dock import MAX_DOCK_ENTRIES

        factory = RequestFactory()
        request = factory.get("/")
        request.session = self.client.session
        for i in range(MAX_DOCK_ENTRIES + 2):
            dock_minimize(request, "item", i, f"Item {i}")
        self.assertLessEqual(len(dock_list(request)), MAX_DOCK_ENTRIES)


class MatrixViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser("owner", "owner@test", "pass")
        self.client = Client()
        self.client.login(username="owner", password="pass")
        call_command("seed_data", "--flush")

    def test_matrix_surface_loads(self):
        response = self.client.get(reverse("canvas-matrix"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Backlog Matrix", response.content)

    def test_matrix_lazy_children(self):
        epic = WorkspaceContainer.objects.get(slug="lifeos-v2")
        response = self.client.get(reverse("matrix-children", args=[epic.pk]))
        self.assertEqual(response.status_code, 200)

    def test_item_patch_field_htmx(self):
        item = ExecutionItem.objects.get(title="Build cockpit shell + Home bento")
        response = self.client.post(
            reverse("item-patch-field", args=[item.pk]),
            {"field": "priority", "value": "1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.priority, SystemEnums.PriorityLevel.CRITICAL)

    def test_item_patch_field_requires_csrf_in_browser(self):
        """Simulate browser POST with X-CSRFToken header."""
        item = ExecutionItem.objects.get(title="Build cockpit shell + Home bento")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username="owner", password="pass")
        csrf_client.get(reverse("canvas-matrix"))
        csrf = csrf_client.cookies["csrftoken"].value
        response = csrf_client.post(
            reverse("item-patch-field", args=[item.pk]),
            {"field": "priority", "value": "2"},
            HTTP_HX_REQUEST="true",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.priority, SystemEnums.PriorityLevel.HIGH)

    def test_bulk_requires_checked_items_message(self):
        response = self.client.post(
            reverse("items-bulk"),
            {"action": "status", "value": SystemEnums.ItemStatus.BLOCKED},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)

    def test_drawer_item_loads(self):
        item = ExecutionItem.objects.first()
        response = self.client.get(reverse("drawer-item", args=[item.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertIn(item.title.encode(), response.content)
        self.assertEqual(response.headers.get("HX-Trigger"), "drawer-open")
        self.assertContains(response, 'name="value"')
        self.assertContains(response, 'return": "drawer"')

    def test_drawer_container_loads(self):
        container = WorkspaceContainer.objects.get(slug="lifeos-v2")
        response = self.client.get(
            reverse("drawer-container", args=[container.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"LifeOS V2 Rewrite", response.content)
        self.assertEqual(response.headers.get("HX-Trigger"), "drawer-open")
        self.assertContains(response, "para_state")

    def test_bulk_status_update(self):
        items = list(ExecutionItem.objects.filter(is_deleted=False)[:2])
        response = self.client.post(
            reverse("items-bulk"),
            {
                "action": "status",
                "value": SystemEnums.ItemStatus.BLOCKED,
                "item_ids": [str(i.pk) for i in items],
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        for item in items:
            item.refresh_from_db()
            self.assertEqual(item.status, SystemEnums.ItemStatus.BLOCKED)

    def test_drawer_patch_item_priority(self):
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        response = self.client.post(
            reverse("item-patch-field", args=[item.pk]),
            {"field": "priority", "value": "1", "return": "drawer"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.priority, 1)
        self.assertContains(response, "drawer-item")
        self.assertContains(response, 'selected')

    def test_drawer_patch_item_notes(self):
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        response = self.client.post(
            reverse("item-patch-field", args=[item.pk]),
            {"field": "notes", "value": "Quick drawer note", "return": "drawer"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.notes, "Quick drawer note")
        self.assertContains(response, "Quick drawer note")

    def test_drawer_patch_container_title(self):
        container = WorkspaceContainer.objects.get(slug="lifeos-v2")
        response = self.client.post(
            reverse("container-patch-field", args=[container.pk]),
            {"field": "title", "value": "LifeOS V2 Rewrite (edited)", "return": "drawer"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        container.refresh_from_db()
        self.assertEqual(container.title, "LifeOS V2 Rewrite (edited)")
        self.assertContains(response, "LifeOS V2 Rewrite (edited)")

    def test_drawer_patch_blocked_complete_shows_error(self):
        from lifeos_app.models import ItemDependencyLink

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
        response = self.client.post(
            reverse("item-patch-field", args=[blocked.pk]),
            {
                "field": "status",
                "value": SystemEnums.ItemStatus.COMPLETED,
                "return": "drawer",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "prerequisites", status_code=422)
