# ==============================================================================
# File: lifeos_app/services/owner.py
# Description: Single-owner account helpers for LifeOS V2
# Component: Core / Auth Services
# Version: 2.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""Owner superuser provisioning for the single-user cockpit."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


def owner_exists() -> bool:
    """Return True when at least one superuser account exists."""
    return get_user_model().objects.filter(is_superuser=True).exists()


def create_owner_user(
    username: str,
    password: str,
    email: str = "",
    *,
    force: bool = False,
) -> tuple[object, bool]:
    """Create or update the owner superuser.

    Returns (user, created). Raises ValidationError on invalid input.
    When an owner already exists and force is False, raises ValidationError.
    """
    User = get_user_model()
    username = (username or "").strip()
    email = (email or "").strip()

    if not username:
        raise ValidationError("Username is required.")
    if not password:
        raise ValidationError("Password is required.")

    if owner_exists() and not force:
        raise ValidationError(
            "An owner account already exists. Use --force to reset credentials via CLI."
        )

    validate_password(password, user=None)

    user, created = User.objects.get_or_create(
        username=username,
        defaults={"email": email, "is_staff": True, "is_superuser": True},
    )
    user.email = email or user.email
    user.is_staff = True
    user.is_superuser = True
    user.set_password(password)
    user.save()
    return user, created
