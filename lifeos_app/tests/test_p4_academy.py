# ==============================================================================
# File: lifeos_app/tests/test_p4_academy.py
# Description: P4-SURF-ACADEMY Hub tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Academy Hub — cert meters, course tree progress, drawer academy fields."""

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import Certification, SystemEnums, WorkspaceContainer
from lifeos_app.services.academy import (
    build_academy_page,
    build_cert_progress,
    build_course_forest,
    completion_percent,
    is_academy_surface,
)


class AcademyServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_cert_progress_from_seed(self):
        rows = build_cert_progress()
        self.assertTrue(rows)
        sec = next(r for r in rows if "Security+" in r.certification.name)
        # specialization 12 + course 8 + module 2
        self.assertAlmostEqual(sec.credits_earned, 22.0)
        self.assertEqual(sec.credits_required, 40.0)
        self.assertEqual(sec.percent, 55)
        self.assertFalse(sec.is_complete)

    def test_course_forest_includes_specialization(self):
        forest = build_course_forest()
        titles = [n.container.title for n in forest]
        self.assertTrue(any("Cybersecurity" in t for t in titles))
        root = next(n for n in forest if "Cybersecurity" in n.container.title)
        self.assertTrue(root.children)  # course under specialization
        self.assertGreaterEqual(root.item_total, 1)

    def test_completion_percent(self):
        self.assertEqual(completion_percent(0, 0), 0)
        self.assertEqual(completion_percent(1, 2), 50)
        self.assertEqual(completion_percent(2, 2), 100)

    def test_is_academy_surface(self):
        course = WorkspaceContainer.objects.get(slug="secplus-course")
        self.assertTrue(is_academy_surface(course))
        epic = WorkspaceContainer.objects.get(slug="lifeos-v2")
        self.assertFalse(is_academy_surface(epic))

    def test_build_academy_page_context(self):
        ctx = build_academy_page()
        self.assertEqual(ctx["surface"], "academy")
        self.assertTrue(ctx["cert_progress"])
        self.assertTrue(ctx["course_forest"])
        self.assertGreater(ctx["academy_container_count"], 0)


class AcademySurfaceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_academy_renders(self):
        response = self.client.get(reverse("canvas-academy"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Academy Hub")
        self.assertContains(response, "Security+")
        self.assertContains(response, "Cybersecurity Specialization")
        self.assertContains(response, "Course tree")
        self.assertNotContains(response, "lands in a later phase")

    def test_container_drawer_shows_academy_fields(self):
        course = WorkspaceContainer.objects.get(slug="secplus-course")
        response = self.client.get(reverse("drawer-container", args=[course.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Academy")
        self.assertContains(response, "Udemy")
        self.assertContains(response, "Security+")

    def test_non_academy_drawer_hides_academy_block(self):
        epic = WorkspaceContainer.objects.get(slug="lifeos-v2")
        response = self.client.get(reverse("drawer-container", args=[epic.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, ">Academy</div>")
