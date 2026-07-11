# ==============================================================================
# File: lifeos_app/tasks.py
# Description: Celery tasks — reminder sweep + telemetry warm (P5-04)
# Component: Jobs / Celery
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Periodic jobs scheduled by Celery Beat (cron remains a valid fallback)."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="lifeos_app.sweep_reminders")
def sweep_reminders_task() -> dict:
    """Dispatch due ReminderDispatch rows via outbound webhook."""
    from lifeos_app.services.notify import sweep_reminders

    result = sweep_reminders()
    payload = {
        "examined": result.examined,
        "sent": result.sent,
        "failed": result.failed,
        "skipped": result.skipped,
    }
    logger.info("sweep_reminders %s", payload)
    return payload


@shared_task(name="lifeos_app.warm_telemetry")
def warm_telemetry_task() -> dict:
    """Refresh weather + space-weather caches off the request path."""
    from lifeos_app.services.telemetry.hud import warm_telemetry_caches

    payload = warm_telemetry_caches()
    logger.info("warm_telemetry %s", payload)
    return payload


@shared_task(name="lifeos_app.compute_stability")
def compute_stability_task() -> dict:
    """Daily Stability Index snapshot (Beat crontab)."""
    from lifeos_app.services.stability import compute_stability_for_date, today_local

    snap = compute_stability_for_date(today_local())
    payload = {
        "date": str(snap.date),
        "index_score": snap.index_score,
        "band": snap.band,
    }
    logger.info("compute_stability %s", payload)
    return payload


@shared_task(name="lifeos_app.fire_reminder")
def fire_reminder_task(dispatch_id: int) -> dict:
    """ETA delivery for a single ReminderDispatch (P5-05)."""
    from lifeos_app.services.reminders import fire_single_dispatch

    payload = fire_single_dispatch(dispatch_id)
    logger.info("fire_reminder id=%s %s", dispatch_id, payload)
    return payload
