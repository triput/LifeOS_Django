# ==============================================================================
# File: lifeos_app/tests/test_p3_appearance.py
# Description: BL-UI-002 / BL-UI-003 appearance tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Theme switcher and domain/tag color settings."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import AppSettings, DomainCategory, Tag
from lifeos_app.services.appearance import normalize_hex_color, save_appearance_settings
from lifeos_app.services.themes import THEME_SOLARIZED_DARK, resolve_theme_slug


class ThemeTests(TestCase):
    def test_resolve_legacy_dark(self):
        self.assertEqual(resolve_theme_slug("Dark"), "hybrid_dark")

    def test_resolve_solarized(self):
        self.assertEqual(resolve_theme_slug(THEME_SOLARIZED_DARK), THEME_SOLARIZED_DARK)

    def test_save_theme_mode(self):
        result = save_appearance_settings(
            theme_mode=THEME_SOLARIZED_DARK,
            domain_colors={},
            tag_colors={},
        )
        self.assertTrue(result.ok)
        solo = AppSettings.get_solo()
        self.assertEqual(solo.theme_mode, THEME_SOLARIZED_DARK)


class ColorPickerTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush")

    def test_normalize_hex(self):
        self.assertEqual(normalize_hex_color("#aabbcc", fallback="#000000"), "#AABBCC")
        self.assertEqual(normalize_hex_color("bad", fallback="#112233"), "#112233")

    def test_save_domain_and_tag_colors(self):
        domain = DomainCategory.objects.first()
        tag = Tag.objects.first()
        assert domain and tag
        result = save_appearance_settings(
            theme_mode="hybrid_dark",
            domain_colors={domain.pk: "#FF0000"},
            tag_colors={tag.pk: "#00FF00"},
        )
        self.assertTrue(result.ok)
        domain.refresh_from_db()
        tag.refresh_from_db()
        self.assertEqual(domain.color, "#FF0000")
        self.assertEqual(tag.color, "#00FF00")


class AppearanceViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_settings_shows_appearance_section(self):
        response = self.client.get(reverse("canvas-settings"), {"tab": "appearance"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Appearance")
        self.assertContains(response, "Hybrid Dark")
        self.assertContains(response, "domain_color_")
        self.assertContains(response, "Reset all")

    def test_appearance_save_sets_hx_refresh(self):
        domain = DomainCategory.objects.first()
        tag = Tag.objects.first()
        assert domain and tag
        response = self.client.post(
            reverse("settings-appearance-save"),
            {
                "theme_mode": "light",
                "settings_tab": "appearance",
                "domain_color_%s" % domain.pk: "#123456",
                "tag_color_%s" % tag.pk: "#654321",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")
        self.assertEqual(AppSettings.get_solo().theme_mode, "light")

    def test_reset_single_domain_color(self):
        domain = DomainCategory.objects.get(slug="tech")
        domain.color = "#FF0000"
        domain.save(update_fields=["color"])
        from lifeos_app.services.appearance import reset_domain_colors

        result = reset_domain_colors(domain_id=domain.pk)
        self.assertTrue(result.ok)
        domain.refresh_from_db()
        self.assertEqual(domain.color, "#8B9EF5")

    def test_reset_all_tag_colors(self):
        tag = Tag.objects.first()
        assert tag
        tag.color = "#000000"
        tag.save(update_fields=["color"])
        from lifeos_app.services.appearance import reset_tag_colors

        result = reset_tag_colors(tag_id=None)
        self.assertTrue(result.ok)
        tag.refresh_from_db()
        self.assertNotEqual(tag.color, "#000000")

    def test_reset_color_htmx(self):
        domain = DomainCategory.objects.get(slug="tech")
        domain.color = "#FF0000"
        domain.save(update_fields=["color"])
        response = self.client.post(
            reverse("settings-appearance-reset-color"),
            {"kind": "domain", "pk": str(domain.pk)},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        domain.refresh_from_db()
        self.assertEqual(domain.color, "#8B9EF5")
        self.assertContains(response, "Reset")

    def test_shell_data_theme_follows_saved_mode(self):
        solo = AppSettings.get_solo()
        solo.theme_mode = THEME_SOLARIZED_DARK
        solo.save(update_fields=["theme_mode"])
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'data-theme="solarized_dark"')
