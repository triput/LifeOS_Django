# ==============================================================================
# File: Procfile
# Description: Process definition file for Railway deployment
# Component: Deployment Configuration
# Version: 1.0 (Gold Master)
# Created: 2026-07-01
# Last Update: 2026-07-01
# ==============================================================================
web: python manage.py migrate && gunicorn lifeos_django.wsgi:application
