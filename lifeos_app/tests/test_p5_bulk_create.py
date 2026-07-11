# ==============================================================================
# File: lifeos_app/tests/test_p5_bulk_create.py
# Description: P5 / BL-BULK-001 bulk spreadsheet + CSV create tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Bulk create service, CSV parse, and Bulk Add surface."""

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import ExecutionItem, ItemContainerLink, WorkspaceContainer
from lifeos_app.services.bulk_create import (
    commit_bulk_rows,
    parse_delimited_text,
    rows_from_dicts,
    template_csv_text,
)
from lifeos_app.services.cmd import preview_command


class BulkCreateServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_parse_csv_with_header(self):
        text = template_csv_text()
        rows = parse_delimited_text(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].kind.lower(), "container")
        self.assertEqual(rows[1].parent, "r1")

    def test_commit_nested_container_and_item(self):
        rows = rows_from_dicts(
            [
                {
                    "row_id": "r1",
                    "kind": "container",
                    "title": "Bulk Epic Alpha",
                    "type": "EPIC",
                    "slug": "bulk-epic-alpha",
                    "domain": "tech",
                },
                {
                    "row_id": "r2",
                    "kind": "item",
                    "title": "Bulk leaf under alpha",
                    "type": "TASK",
                    "parent": "r1",
                    "status": "BACKLOG",
                    "priority": "2",
                    "estimate": "45m",
                    "tags": "deep-work",
                },
            ]
        )
        result = commit_bulk_rows(rows)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.created_containers, 1)
        self.assertEqual(result.created_items, 1)
        epic = WorkspaceContainer.objects.get(slug="bulk-epic-alpha")
        item = ExecutionItem.objects.get(title="Bulk leaf under alpha")
        self.assertEqual(item.estimated_minutes, 45)
        self.assertEqual(item.priority, 2)
        link = ItemContainerLink.objects.get(item=item, is_primary=True)
        self.assertEqual(link.container_id, epic.pk)
        self.assertTrue(item.tags.filter(name__iexact="deep-work").exists())

    def test_soft_fail_keeps_good_rows(self):
        rows = rows_from_dicts(
            [
                {
                    "kind": "item",
                    "title": "Good bulk item",
                    "type": "TASK",
                    "parent": "inbox",
                    "status": "INBOX",
                },
                {
                    "kind": "item",
                    "title": "Bad parent item",
                    "type": "TASK",
                    "parent": "no-such-container-xyz",
                },
            ]
        )
        result = commit_bulk_rows(rows)
        self.assertEqual(result.created_items, 1)
        self.assertEqual(result.failed, 1)
        self.assertTrue(ExecutionItem.objects.filter(title="Good bulk item").exists())
        self.assertFalse(ExecutionItem.objects.filter(title="Bad parent item").exists())

    def test_parent_existing_slug(self):
        rows = parse_delimited_text(
            "kind,title,type,parent,status\n"
            "item,Under lifeos v2,TASK,#lifeos-v2,PLANNED\n"
        )
        result = commit_bulk_rows(rows)
        self.assertEqual(result.failed, 0)
        item = ExecutionItem.objects.get(title="Under lifeos v2")
        home = item.primary_container()
        self.assertIsNotNone(home)
        self.assertEqual(home.slug, "lifeos-v2")


class BulkCreateSurfaceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_bulk_surface_renders(self):
        response = self.client.get(reverse("canvas-bulk"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bulk Add")
        self.assertContains(response, "Download template CSV")
        self.assertContains(response, "Commit rows")

    def test_template_csv_download(self):
        response = self.client.get(reverse("bulk-template-csv"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("row_id,kind,title", body)

    def test_commit_from_grid_json(self):
        payload = [
            {
                "row_id": "r9",
                "kind": "container",
                "title": "Grid Epic",
                "type": "PROJECT",
                "slug": "grid-epic",
            },
            {
                "kind": "item",
                "title": "Grid task",
                "type": "TASK",
                "parent": "r9",
                "status": "BACKLOG",
                "estimate": "1h",
            },
        ]
        import json

        response = self.client.post(
            reverse("bulk-commit"),
            {"rows_json": json.dumps(payload)},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Commit report")
        self.assertTrue(WorkspaceContainer.objects.filter(slug="grid-epic").exists())
        self.assertTrue(ExecutionItem.objects.filter(title="Grid task").exists())

    def test_preview_paste(self):
        response = self.client.post(
            reverse("bulk-preview"),
            {
                "paste_text": "kind,title,type\ncontainer,Paste Epic,EPIC\nitem,Paste Task,TASK\n"
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paste Epic")
        self.assertContains(response, "Paste Task")

    def test_go_bulk_alias(self):
        preview = preview_command("go bulk")
        self.assertEqual(preview.mode, "go")
        self.assertTrue(preview.redirect_url)
        self.assertIn("/canvas/bulk/", preview.redirect_url)
