# ==============================================================================
# File: lifeos_app/apps.py
# Description: Django app config for lifeos_app (V2)
# Component: Core
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
from django.apps import AppConfig


class LifeosAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lifeos_app"
    verbose_name = "LifeOS"
