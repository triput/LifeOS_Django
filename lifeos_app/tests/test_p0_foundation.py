# ==============================================================================
# File: lifeos_app/tests/test_p0_foundation.py
# Description: P0 foundation tests — models, middleware, home, seed_data
# Component: Tests
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Automated coverage for LifeOS V2 P0 foundation."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import (
    AppSettings,
    DomainCategory,
    ExecutionItem,
    FocusSession,
    ItemContainerLink,
    ItemDependencyLink,
    SystemEnums,
    WorkspaceContainer,
)


class ModelFoundationTests(TestCase):
    def test_app_settings_singleton(self):
        a = AppSettings.get_solo()
        b = AppSettings.get_solo()
        self.assertEqual(a.pk, 1)
        self.assertEqual(b.pk, 1)

    def test_container_slug_and_archive_flag(self):
        c = WorkspaceContainer.objects.create(
            title="Demo Epic",
            container_type=SystemEnums.ContainerType.EPIC,
            para_state=SystemEnums.PARACategory.ARCHIVE,
        )
        self.assertTrue(c.slug)
        self.assertTrue(c.is_archived)

    def test_primary_container_link_and_dependency(self):
        epic = WorkspaceContainer.objects.create(
            title="E",
            slug="e",
            container_type=SystemEnums.ContainerType.EPIC,
        )
        prereq = ExecutionItem.objects.create(
            title="A",
            status=SystemEnums.ItemStatus.BACKLOG,
        )
        blocked = ExecutionItem.objects.create(
            title="B",
            status=SystemEnums.ItemStatus.BACKLOG,
        )
        ItemContainerLink.objects.create(item=prereq, container=epic, is_primary=True)
        ItemDependencyLink.objects.create(
            from_item=blocked,
            to_item=prereq,
            link_type=SystemEnums.DependencyLinkType.BLOCKS,
        )
        self.assertTrue(blocked.has_unmet_dependencies)
        prereq.status = SystemEnums.ItemStatus.COMPLETED
        prereq.save()
        self.assertFalse(blocked.has_unmet_dependencies)


class SeedDataTests(TestCase):
    def test_seed_data_populates_core_entities(self):
        call_command("seed_data", "--flush")
        self.assertGreaterEqual(DomainCategory.objects.count(), 5)
        self.assertTrue(WorkspaceContainer.objects.filter(slug="inbox").exists())
        self.assertTrue(WorkspaceContainer.objects.filter(slug="today").exists())
        self.assertGreaterEqual(ExecutionItem.objects.count(), 10)
        self.assertTrue(FocusSession.objects.filter(ended_at__isnull=True).exists())
        self.assertTrue(ItemDependencyLink.objects.exists())
        self.assertTrue(ItemContainerLink.objects.filter(is_primary=True).exists())


class HomeViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser("owner", "owner@test", "pass")
        self.client = Client()
        call_command("seed_data", "--flush")

    def test_login_redirects_to_setup_without_owner(self):
        get_user_model().objects.filter(is_superuser=True).delete()
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("setup-owner"))

    def test_setup_creates_owner(self):
        User = get_user_model()
        User.objects.filter(is_superuser=True).delete()
        response = self.client.post(
            reverse("setup-owner"),
            {
                "username": "newowner",
                "email": "new@test",
                "password": "ComplexPass123!",
                "password_confirm": "ComplexPass123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="newowner", is_superuser=True).exists())

    def test_home_requires_auth(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 302)

    def test_home_ok_for_owner(self):
        self.client.login(username="owner", password="pass")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Active Focus")
        self.assertContains(response, "LifeOS")

    def test_non_owner_forbidden(self):
        User = get_user_model()
        User.objects.create_user("guest", "g@test", "pass")
        self.client.login(username="guest", password="pass")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 403)
