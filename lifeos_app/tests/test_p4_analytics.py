# ==============================================================================
# File: lifeos_app/tests/test_p4_analytics.py
# Description: P4-SURF-ANALYTICS velocity / history tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Analytics — stability series, focus rollups, surface render."""

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from lifeos_app.models import StabilitySnapshot
from lifeos_app.services.analytics import (
    DEFAULT_WINDOW_DAYS,
    build_analytics_page,
    build_day_series,
    parse_window_days,
    summarize_series,
)
from lifeos_app.services.cmd import preview_command


class AnalyticsServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")

    def test_parse_window_days(self):
        self.assertEqual(parse_window_days("14"), 14)
        self.assertEqual(parse_window_days("99"), DEFAULT_WINDOW_DAYS)
        self.assertEqual(parse_window_days(None), DEFAULT_WINDOW_DAYS)

    def test_day_series_includes_seed_snapshots(self):
        series = build_day_series(days=14)
        self.assertEqual(len(series), 14)
        with_snap = [p for p in series if p.has_snapshot]
        # Seed writes 4 history rows; timezone boundaries may drop one edge day.
        self.assertGreaterEqual(len(with_snap), 3)
        self.assertTrue(StabilitySnapshot.objects.filter(date=series[-1].local_date).exists())

    def test_summary_counts_bands(self):
        series = build_day_series(days=14)
        summary = summarize_series(series)
        self.assertEqual(summary.days, 14)
        self.assertGreaterEqual(summary.stable_days + summary.behind_days + summary.overloaded_days, 1)
        self.assertGreaterEqual(summary.completions_total, 0)

    def test_build_page_context(self):
        ctx = build_analytics_page(days=14)
        self.assertEqual(ctx["surface"], "analytics")
        self.assertEqual(ctx["window_days"], 14)
        self.assertTrue(ctx["series"])
        self.assertEqual(len(ctx["series_newest_first"]), len(ctx["series"]))


class AnalyticsSurfaceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_analytics_renders(self):
        response = self.client.get(reverse("canvas-analytics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Velocity Deep Dive")
        self.assertContains(response, "Stability index")
        self.assertContains(response, "Daily detail")
        self.assertContains(response, "Focus time")
        # Human-readable focus in summary (not a bare NNNNs total)
        body = response.content.decode()
        self.assertNotRegex(
            body,
            r'Focus</div>\s*<div class="mt-1 font-display text-2xl[^"]*">\d+s</div>',
        )
        self.assertNotContains(response, "lands in a later phase")

    def test_analytics_window_query(self):
        response = self.client.get(reverse("canvas-analytics"), {"days": "7"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="7" selected')

    def test_go_analytics_cmd(self):
        preview = preview_command("go analytics")
        self.assertEqual(preview.mode, "go")
        self.assertIn("/canvas/analytics/", preview.redirect_url or "")
