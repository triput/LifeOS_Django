# ==============================================================================
# File: lifeos_app/tests/test_p4_overview.py
# Description: P4-SURF-OVERVIEW Horizon Overview tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Horizon Overview — active leaves, facets, group-by, pagination."""

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import ExecutionItem, ItemContainerLink, SystemEnums
from lifeos_app.services.overview import (
    OVERVIEW_PAGE_SIZE,
    OverviewFacets,
    active_leaves,
    build_overview_page,
)


class OverviewQueryTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_active_leaves_excludes_completed_by_default(self):
        facets = OverviewFacets()
        qs = active_leaves(facets)
        self.assertFalse(qs.filter(status=SystemEnums.ItemStatus.COMPLETED).exists())
        self.assertTrue(qs.exists())

    def test_active_leaves_excludes_archived_primary(self):
        link = (
            ItemContainerLink.objects.filter(
                is_primary=True,
                item__is_deleted=False,
                item__parent_item__isnull=True,
            )
            .exclude(item__status=SystemEnums.ItemStatus.COMPLETED)
            .select_related("item", "container")
            .first()
        )
        self.assertIsNotNone(link)
        item = link.item
        container = link.container
        container.is_archived = True
        container.para_state = SystemEnums.PARACategory.ARCHIVE
        container.save()
        facets = OverviewFacets()
        self.assertFalse(active_leaves(facets).filter(pk=item.pk).exists())
        facets_inc = OverviewFacets(include_archived=True)
        self.assertTrue(active_leaves(facets_inc).filter(pk=item.pk).exists())

    def test_group_by_urgency(self):
        facets = OverviewFacets(group_by="urgency")
        ctx = build_overview_page(facets)
        self.assertTrue(ctx["groups"])
        labels = {g.label for g in ctx["groups"]}
        self.assertTrue(labels)


class OverviewSurfaceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_overview_renders_leaves(self):
        response = self.client.get(reverse("canvas-overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Horizon Overview")
        self.assertContains(response, "overview-page")
        self.assertNotContains(response, "Phase placeholder")
        # Seed has real task titles
        item = (
            ExecutionItem.objects.filter(is_deleted=False, parent_item__isnull=True)
            .exclude(status=SystemEnums.ItemStatus.COMPLETED)
            .first()
        )
        if item:
            self.assertContains(response, item.title)

    def test_overview_facet_filter(self):
        response = self.client.get(reverse("canvas-overview"), {"status": "IN_PROGRESS"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Horizon Overview")

    def test_overview_group_by_domain(self):
        response = self.client.get(reverse("canvas-overview"), {"group_by": "domain"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Group:")

    def test_overview_pagination_context(self):
        # Ensure page size constant is wired
        facets = OverviewFacets(page=1)
        ctx = build_overview_page(facets)
        self.assertEqual(ctx["page_size"], OVERVIEW_PAGE_SIZE)
        self.assertLessEqual(len(ctx["groups"][0].items), OVERVIEW_PAGE_SIZE)
