# ==============================================================================
# File: lifeos_app/tests/test_p5_templates.py
# Description: P5-02 curated workspace template apply tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""ENG-TEMPLATE — preview counts, apply tree, Cmd+K, Settings catalog."""

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import ExecutionItem, ItemContainerLink, WorkspaceContainer
from lifeos_app.services.cmd import commit_command, preview_command
from lifeos_app.services.templates_workspace import apply_template, preview_template


class TemplateServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_preview_software_epic(self):
        preview = preview_template("software-epic")
        self.assertTrue(preview.ok)
        self.assertEqual(preview.container_count, 2)
        self.assertEqual(preview.item_count, 1)

    def test_preview_unknown(self):
        preview = preview_template("nope-template")
        self.assertFalse(preview.ok)

    def test_apply_creates_tree(self):
        before_c = WorkspaceContainer.objects.count()
        before_i = ExecutionItem.objects.count()
        result = apply_template("software-epic")
        self.assertTrue(result.ok)
        self.assertEqual(result.containers_created, 2)
        self.assertEqual(result.items_created, 1)
        self.assertEqual(WorkspaceContainer.objects.count(), before_c + 2)
        self.assertEqual(ExecutionItem.objects.count(), before_i + 1)
        root = WorkspaceContainer.objects.get(pk=result.root_container_id)
        self.assertEqual(root.container_type, "EPIC")
        sprint = WorkspaceContainer.objects.get(parent=root, container_type="SPRINT")
        item = ExecutionItem.objects.get(title="Define acceptance criteria")
        link = ItemContainerLink.objects.get(item=item, is_primary=True)
        self.assertEqual(link.container_id, sprint.pk)

    def test_apply_course_modules(self):
        result = apply_template("course-modules")
        self.assertTrue(result.ok)
        self.assertEqual(result.containers_created, 2)
        self.assertEqual(result.items_created, 0)
        root = WorkspaceContainer.objects.get(pk=result.root_container_id)
        self.assertEqual(root.container_type, "COURSE")


class TemplateCmdTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_preview_command(self):
        preview = preview_command("template apply software-epic")
        self.assertEqual(preview.mode, "do")
        self.assertIsNotNone(preview.template)
        self.assertTrue(preview.template.ok)
        self.assertIn("container", preview.summary.lower())

    def test_commit_command(self):
        result = commit_command("template apply software-epic")
        self.assertTrue(result.ok)
        self.assertTrue(result.redirect_url)
        self.assertIn("/canvas/matrix/", result.redirect_url)
        self.assertTrue(WorkspaceContainer.objects.filter(title="New Software Epic").exists())


class TemplateSettingsTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_settings_templates_tab(self):
        response = self.client.get(reverse("canvas-settings"), {"tab": "templates"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workspace templates")
        self.assertContains(response, "software-epic")
        self.assertContains(response, "course-modules")
        self.assertContains(response, "template apply")
