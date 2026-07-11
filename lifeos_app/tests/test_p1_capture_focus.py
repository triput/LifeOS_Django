# ==============================================================================
# File: lifeos_app/tests/test_p1_capture_focus.py
# Description: P1 tests — capture parser, focus engine, inbox triage, HTMX cmd
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Automated coverage for LifeOS V2 P1 Capture & Focus."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import (
    ExecutionItem,
    FocusSession,
    ItemContainerLink,
    SystemEnums,
    WorkspaceContainer,
)
from lifeos_app.services.capture import parse_capture
from lifeos_app.services.cmd import commit_command, preview_command
from lifeos_app.services.focus import complete_focus, get_open_session, pause_focus, start_focus
from lifeos_app.services.triage import triage_item


class CaptureParserTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.sprint = WorkspaceContainer.objects.get(slug="p0-foundation")

    def test_parse_container_priority_tags(self):
        preview = parse_capture("#p0-foundation Ship capture p2 @deep-work", tz_name="UTC")
        self.assertEqual(preview.container_slug, "p0-foundation")
        self.assertTrue(preview.container_found)
        self.assertEqual(preview.priority, 2)
        self.assertIn("deep-work", preview.tag_slugs)
        self.assertIn("Ship capture", preview.title)
        self.assertEqual(preview.status, SystemEnums.ItemStatus.BACKLOG)

    def test_unknown_container_warns_inbox(self):
        preview = parse_capture("#nope-sprint Something", tz_name="UTC")
        self.assertFalse(preview.container_found)
        self.assertTrue(any("Unknown container" in w for w in preview.warnings))
        self.assertEqual(preview.status, SystemEnums.ItemStatus.INBOX)


class FocusEngineTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")
        self.shell = ExecutionItem.objects.get(title="Build cockpit shell + Home bento")
        self.focus_item = ExecutionItem.objects.get(title="Implement Focus Engine start/pause/complete")

    def test_start_preempts_open_session(self):
        r1 = start_focus(self.shell)
        self.assertTrue(r1.ok)
        r2 = start_focus(self.focus_item)
        self.assertTrue(r2.ok)
        self.assertEqual(FocusSession.objects.filter(ended_at__isnull=True).count(), 1)
        preempted = FocusSession.objects.filter(end_reason=SystemEnums.FocusEndReason.PREEMPTED).count()
        self.assertEqual(preempted, 1)

    def test_complete_blocked_by_dependency(self):
        start_focus(self.focus_item)
        result = complete_focus(self.focus_item)
        self.assertFalse(result.ok)
        self.assertIn("prerequisites", result.message.lower())
        self.focus_item.refresh_from_db()
        self.assertNotEqual(self.focus_item.status, SystemEnums.ItemStatus.COMPLETED)

    def test_pause_accumulates_time(self):
        start_focus(self.shell)
        session = get_open_session()
        self.assertIsNotNone(session)
        before = self.shell.time_spent_seconds
        pause_focus()
        self.shell.refresh_from_db()
        self.assertGreater(self.shell.time_spent_seconds, before)


class TriageTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")

    def test_triage_moves_to_backlog(self):
        item = ExecutionItem.objects.filter(status=SystemEnums.ItemStatus.INBOX).first()
        result = triage_item(item, "p0-foundation")
        self.assertTrue(result.ok)
        item.refresh_from_db()
        self.assertEqual(item.status, SystemEnums.ItemStatus.BACKLOG)
        self.assertTrue(
            ItemContainerLink.objects.filter(item=item, container__slug="p0-foundation", is_primary=True).exists()
        )


class CmdPaletteViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser("owner", "owner@test", "pass")
        self.client = Client()
        self.client.login(username="owner", password="pass")
        call_command("seed_data", "--flush")

    def test_preview_returns_fragment(self):
        response = self.client.post(reverse("cmd-preview"), {"input": "go inbox"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"inbox", response.content.lower())

    def test_capture_commit_creates_item(self):
        before = ExecutionItem.objects.count()
        result = commit_command("Inbox triage test p3 @quick-win")
        self.assertTrue(result.ok)
        self.assertEqual(ExecutionItem.objects.count(), before + 1)
        item = ExecutionItem.objects.get(title="Inbox triage test")
        self.assertEqual(item.status, SystemEnums.ItemStatus.INBOX)

    def test_go_preview_has_redirect(self):
        preview = preview_command("go matrix")
        self.assertEqual(preview.mode, "go")
        self.assertIsNotNone(preview.redirect_url)

    def test_inbox_surface_loads(self):
        response = self.client.get(reverse("canvas-inbox"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Inbox Triage", response.content)

    def test_focus_start_fragment(self):
        item = ExecutionItem.objects.get(title="Build cockpit shell + Home bento")
        response = self.client.post(
            reverse("focus-start", args=[item.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Active Focus", response.content)
