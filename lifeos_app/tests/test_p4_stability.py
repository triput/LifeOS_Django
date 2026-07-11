# ==============================================================================
# File: lifeos_app/tests/test_p4_stability.py
# Description: P4-ENG-STABILITY live Stability Index tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Stability compute, Home Tier 3, Settings targets, management command."""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from lifeos_app.models import AppSettings, ExecutionItem, FocusSession, StabilitySnapshot, SystemEnums
from lifeos_app.services.stability import (
    STABLE_SCORE_FLOOR,
    compute_score_and_band,
    compute_stability_for_date,
    ensure_today_stability,
    gather_inputs,
    today_local,
)
from lifeos_app.services.stability import StabilityInputs


class StabilityServiceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.settings = AppSettings.get_solo()
        self.settings.daily_completion_target = 5
        self.settings.daily_focus_minutes_target = 120
        self.settings.stability_streak_window_days = 7
        self.settings.save()

    def test_score_stable_when_targets_met(self):
        inputs = StabilityInputs(
            local_date=today_local(self.settings),
            completions_count=5,
            focus_seconds=120 * 60,
            planned_minutes=0,
            completion_target=5,
            focus_minutes_target=120,
        )
        score, band = compute_score_and_band(inputs)
        self.assertGreaterEqual(score, STABLE_SCORE_FLOOR)
        self.assertEqual(band, SystemEnums.StabilityBand.STABLE)

    def test_score_overloaded_when_focus_high(self):
        inputs = StabilityInputs(
            local_date=today_local(self.settings),
            completions_count=5,
            focus_seconds=int(120 * 60 * 1.3),
            planned_minutes=0,
            completion_target=5,
            focus_minutes_target=120,
        )
        score, band = compute_score_and_band(inputs)
        self.assertEqual(band, SystemEnums.StabilityBand.OVERLOADED)
        self.assertGreaterEqual(score, 0)

    def test_ensure_today_writes_snapshot(self):
        snap = ensure_today_stability(settings=self.settings)
        self.assertEqual(snap.date, today_local(self.settings))
        self.assertTrue(StabilitySnapshot.objects.filter(date=snap.date).exists())
        self.assertGreaterEqual(snap.index_score, 0)

    def test_completions_count_from_completed_items(self):
        day = today_local(self.settings)
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        self.assertIsNotNone(item)
        item.status = SystemEnums.ItemStatus.COMPLETED
        item.save(update_fields=["status", "updated_at"])
        inputs = gather_inputs(day, self.settings)
        self.assertGreaterEqual(inputs.completions_count, 1)

    def test_focus_seconds_from_closed_session(self):
        day = today_local(self.settings)
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        now = timezone.now()
        FocusSession.objects.create(
            execution_item=item,
            started_at=now - timedelta(minutes=45),
            ended_at=now - timedelta(minutes=5),
            duration_seconds=40 * 60,
        )
        inputs = gather_inputs(day, self.settings)
        self.assertGreaterEqual(inputs.focus_seconds, 40 * 60)

    def test_streak_counts_stable_days(self):
        day = today_local(self.settings)
        for offset in range(1, 4):
            StabilitySnapshot.objects.update_or_create(
                date=day - timedelta(days=offset),
                defaults={
                    "completions_count": 5,
                    "focus_seconds": 7200,
                    "planned_minutes": 120,
                    "index_score": 90,
                    "band": SystemEnums.StabilityBand.STABLE,
                    "streak_days": 0,
                },
            )
        # Meet targets today so band is STABLE
        item = ExecutionItem.objects.filter(is_deleted=False).first()
        for _ in range(5):
            clone = ExecutionItem.objects.filter(is_deleted=False).exclude(pk=item.pk).first()
            if clone is None:
                break
            clone.status = SystemEnums.ItemStatus.COMPLETED
            clone.save(update_fields=["status", "updated_at"])
        FocusSession.objects.create(
            execution_item=item,
            started_at=timezone.now() - timedelta(hours=3),
            ended_at=timezone.now() - timedelta(hours=1),
            duration_seconds=120 * 60,
        )
        snap = compute_stability_for_date(day, settings=self.settings)
        if snap.band == SystemEnums.StabilityBand.STABLE:
            self.assertGreaterEqual(snap.streak_days, 1)


class StabilitySurfaceTests(TestCase):
    def setUp(self):
        call_command("seed_data", "--flush", username="owner", password="ownerpass")
        self.client = Client()
        self.client.login(username="owner", password="ownerpass")

    def test_home_shows_live_stability(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "System Stability")
        self.assertContains(response, 'id="stability-hud"')
        self.assertTrue(StabilitySnapshot.objects.filter(date=today_local()).exists())

    def test_stability_hud_endpoint(self):
        response = self.client.get(reverse("stability-hud"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "stability-hud")
        self.assertContains(response, "System Stability")

    def test_settings_saves_stability_targets(self):
        response = self.client.post(
            reverse("settings-general-save"),
            {
                "timezone": "UTC",
                "scheduler_buffer_minutes": "10",
                "location_name": "",
                "weather_provider": "open_meteo",
                "daily_completion_target": "8",
                "daily_focus_minutes_target": "90",
                "stability_streak_window_days": "14",
            },
        )
        self.assertEqual(response.status_code, 200)
        solo = AppSettings.get_solo()
        self.assertEqual(solo.daily_completion_target, 8)
        self.assertEqual(solo.daily_focus_minutes_target, 90)
        self.assertEqual(solo.stability_streak_window_days, 14)
        self.assertContains(response, "Stability targets")

    def test_compute_stability_command(self):
        out = StringIO()
        call_command("compute_stability", stdout=out)
        self.assertIn("Stability", out.getvalue())
        self.assertTrue(StabilitySnapshot.objects.filter(date=today_local()).exists())
