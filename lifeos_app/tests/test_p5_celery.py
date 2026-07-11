# ==============================================================================
# File: lifeos_app/tests/test_p5_celery.py
# Description: P5-04 Celery Beat task + schedule tests
# Component: Tests
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Celery tasks run eagerly in tests; Beat schedule is registered."""

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.conf import settings

from lifeos_app.tasks import (
    compute_stability_task,
    sweep_reminders_task,
    warm_telemetry_task,
)


class CeleryBeatTests(TestCase):
    def test_beat_schedule_registers_core_jobs(self):
        schedule = settings.CELERY_BEAT_SCHEDULE
        tasks = {entry["task"] for entry in schedule.values()}
        self.assertIn("lifeos_app.sweep_reminders", tasks)
        self.assertIn("lifeos_app.warm_telemetry", tasks)
        self.assertIn("lifeos_app.compute_stability", tasks)

    def test_task_always_eager_under_tests(self):
        self.assertTrue(settings.CELERY_TASK_ALWAYS_EAGER)

    @patch("lifeos_app.services.notify.sweep_reminders")
    def test_sweep_reminders_task(self, mock_sweep):
        from lifeos_app.services.notify import SweepResult

        mock_sweep.return_value = SweepResult(examined=2, sent=1, failed=0, skipped=1)
        result = sweep_reminders_task.run()
        self.assertEqual(result["examined"], 2)
        self.assertEqual(result["sent"], 1)
        mock_sweep.assert_called_once()

    @patch("lifeos_app.services.telemetry.hud.warm_telemetry_caches")
    def test_warm_telemetry_task(self, mock_warm):
        mock_warm.return_value = {
            "weather_provider": "open_meteo",
            "weather_error": "",
            "space_error": "",
            "kp_index": 2.0,
        }
        result = warm_telemetry_task.run()
        self.assertEqual(result["weather_provider"], "open_meteo")
        mock_warm.assert_called_once()

    @patch("lifeos_app.services.stability.compute_stability_for_date")
    @patch("lifeos_app.services.stability.today_local")
    def test_compute_stability_task(self, mock_today, mock_compute):
        from datetime import date
        from types import SimpleNamespace

        mock_today.return_value = date(2026, 7, 10)
        mock_compute.return_value = SimpleNamespace(
            date=date(2026, 7, 10),
            index_score=72.0,
            band="steady",
        )
        result = compute_stability_task.run()
        self.assertEqual(result["date"], "2026-07-10")
        self.assertEqual(result["index_score"], 72.0)

    @patch("lifeos_app.tasks.warm_telemetry_task.run")
    @patch("lifeos_app.tasks.sweep_reminders_task.run")
    def test_run_beat_jobs_command(self, mock_sweep_run, mock_warm_run):
        mock_sweep_run.return_value = {"examined": 0}
        mock_warm_run.return_value = {"weather_provider": "none"}
        call_command("run_beat_jobs")
        mock_sweep_run.assert_called_once()
        mock_warm_run.assert_called_once()
