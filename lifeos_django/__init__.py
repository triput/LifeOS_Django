# ==============================================================================
# File: lifeos_django/__init__.py
# Description: Ensure Celery app loads with Django (P5-04)
# Component: Core
# Version: 1.0 (Gold Master)
# Created: 2026-07-10
# Last Update: 2026-07-10
# ==============================================================================
"""Project package — import Celery app so ``shared_task`` binds on worker start."""

from .celery import app as celery_app

__all__ = ("celery_app",)
