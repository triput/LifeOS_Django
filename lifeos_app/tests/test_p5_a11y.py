# ==============================================================================
# File: lifeos_app/tests/test_p5_a11y.py
# Description: P5-06 accessibility pass smoke tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-11
# Last Update: 2026-07-11
# ==============================================================================
"""Shell landmarks, SR status cues, reduced-motion CSS, due labels."""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.template import Context, Template
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from lifeos_app.models import ExecutionItem, SystemEnums


class AccessibilityPassTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        user = get_user_model().objects.get(username="owner")
        self.client.force_login(user)

    def test_home_has_skip_link_and_main(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('href="#main-canvas"', body)
        self.assertIn("Skip to main content", body)
        self.assertIn('id="main-canvas"', body)
        self.assertIn('role="dialog"', body)
        self.assertIn('aria-label="Command palette"', body)
        self.assertIn('aria-label="Cockpit surfaces"', body)

    def test_themes_css_has_a11y_utilities(self):
        css_path = Path(__file__).resolve().parents[1] / "static" / "lifeos" / "themes.css"
        css = css_path.read_text(encoding="utf-8")
        self.assertIn(".sr-only", css)
        self.assertIn(".skip-link", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("prefers-reduced-motion", css)

    def test_status_cue_renders_sr_only(self):
        item = ExecutionItem.objects.create(
            title="A11y item",
            status=SystemEnums.ItemStatus.PLANNED,
            due_at=timezone.now(),
        )
        tpl = Template(
            "{% load lifeos_extras %}"
            "{% due_urgency_label item as due_lbl %}"
            "{% include 'partials/a11y_status_cue.html' with status=item.status "
            "status_label=item.get_status_display due_label=due_lbl %}"
        )
        html = tpl.render(Context({"item": item}))
        self.assertIn("sr-only", html)
        self.assertIn("Status:", html)
        self.assertIn('aria-hidden="true"', html)

    def test_matrix_row_includes_status_sr(self):
        response = self.client.get(reverse("canvas-matrix"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("sr-only", body)
        self.assertIn("Status:", body)
