# ==============================================================================
# File: lifeos_app/tests/test_p4_views.py
# Description: P4-ENG-VIEWS saved facet presets tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Saved views — persist facets, go view, Cmd+K, facet bar save."""

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import SavedView, SystemEnums
from lifeos_app.services.cmd import commit_command, preview_command
from lifeos_app.services.saved_views import build_view_url, get_view, save_view


class SavedViewsServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_seed_views_exist(self):
        self.assertTrue(SavedView.objects.filter(slug="tech-wip").exists())
        self.assertTrue(SavedView.objects.filter(slug="academy-labs").exists())

    def test_build_view_url_includes_params(self):
        view = SavedView.objects.get(slug="tech-wip")
        url = build_view_url(view)
        self.assertIn("/canvas/matrix/", url)
        self.assertIn("domain=tech", url)

    def test_save_view_create_and_update(self):
        result = save_view(
            title="My Board Filter",
            target_surface=SystemEnums.SavedViewSurface.BOARD,
            query_params={"domain": "home", "mode": "stack"},
            is_pinned=True,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.view.slug, "my-board-filter")
        again = save_view(
            title="My Board Filter",
            target_surface=SystemEnums.SavedViewSurface.BOARD,
            query_params={"domain": "tech"},
            slug="my-board-filter",
        )
        self.assertTrue(again.ok)
        result.view.refresh_from_db()
        self.assertEqual(result.view.query_params.get("domain"), "tech")

    def test_go_view_cmd_preview(self):
        preview = preview_command("go view tech-wip")
        self.assertEqual(preview.mode, "go")
        self.assertIsNotNone(preview.redirect_url)
        self.assertIn("matrix", preview.redirect_url)

    def test_save_view_cmd_commit(self):
        result = commit_command(
            "save view Cmd Snapshot",
            view_surface="overview",
            view_query_string="domain=academy&tag=lab",
        )
        self.assertTrue(result.ok)
        view = get_view("cmd-snapshot")
        self.assertIsNotNone(view)
        self.assertEqual(view.target_surface, "overview")
        self.assertEqual(view.query_params.get("domain"), "academy")


class SavedViewsSurfaceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_matrix_shows_saved_views_bar(self):
        response = self.client.get(reverse("canvas-matrix"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "saved-views-bar")
        self.assertContains(response, "Tech WIP")
        self.assertContains(response, "Save view as")

    def test_overview_shows_academy_labs_in_dropdown(self):
        response = self.client.get(reverse("canvas-overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Academy Labs")

    def test_save_from_facet_bar(self):
        response = self.client.post(
            reverse("saved-view-save"),
            {
                "title": "Facet Snapshot",
                "surface": "matrix",
                "query_string": "domain=tech&status=PLANNED",
                "is_pinned": "1",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        view = SavedView.objects.get(slug="facet-snapshot")
        self.assertEqual(view.target_surface, "matrix")
        self.assertTrue(view.is_pinned)
        self.assertEqual(view.query_params.get("status"), "PLANNED")

    def test_go_view_redirect(self):
        response = self.client.get(reverse("saved-view-go", args=["tech-wip"]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/canvas/matrix/", response["Location"])
        self.assertIn("domain=tech", response["Location"])

    def test_go_view_htmx(self):
        response = self.client.get(
            reverse("saved-view-go", args=["academy-labs"]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn("/canvas/overview/", response["HX-Redirect"])
