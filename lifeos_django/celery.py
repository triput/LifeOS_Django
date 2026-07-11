# ==============================================================================
# File: lifeos_django/celery.py
# Description: Celery application for LifeOS Beat + worker (P5-04)
# Component: Core / Jobs
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Celery entrypoint — ``celery -A lifeos_django worker -B``."""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lifeos_django.settings")

app = Celery("lifeos")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
