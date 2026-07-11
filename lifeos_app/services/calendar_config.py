# ==============================================================================
# File: lifeos_app/services/calendar_config.py
# Description: Resolve calendar OAuth client config (Google + Microsoft)
# Component: Services / Calendar
# Version: 1.1 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""OAuth client credentials for calendar providers — never committed to git."""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from lifeos_app.models import AppSettings, SystemEnums


@dataclass(frozen=True)
class OAuthConfig:
    """OAuth web client credentials for a calendar provider."""

    client_id: str
    client_secret: str
    redirect_uri: str = ""
    source: str = "none"  # appsettings | env | none
    provider: str = SystemEnums.CalendarProvider.GOOGLE


def clean_secret(value: str) -> str:
    """Strip whitespace and optional surrounding quotes from pasted credentials."""
    stripped = (value or "").strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        return stripped[1:-1].strip()
    return stripped


def _non_empty(*values: str) -> str:
    for value in values:
        stripped = clean_secret(value)
        if stripped:
            return stripped
    return ""


def _normalize_provider(provider: str | None) -> str:
    if provider in {SystemEnums.CalendarProvider.GOOGLE, SystemEnums.CalendarProvider.MICROSOFT}:
        return provider
    return SystemEnums.CalendarProvider.GOOGLE


def get_oauth_config(
    *,
    provider: str | None = None,
    redirect_uri_override: str = "",
) -> OAuthConfig:
    """
    Load OAuth client config for Google or Microsoft.

    Priority: AppSettings (DB) → Django settings (env / .env). Redirect URI may
    be supplied at runtime (e.g. from the incoming request) when not stored.
    """
    provider = _normalize_provider(provider)
    solo = AppSettings.get_solo()
    if provider == SystemEnums.CalendarProvider.MICROSOFT:
        db_id = clean_secret(solo.microsoft_oauth_client_id or "")
        db_secret = clean_secret(solo.microsoft_oauth_client_secret or "")
        env_id = clean_secret(getattr(settings, "MICROSOFT_OAUTH_CLIENT_ID", ""))
        env_secret = clean_secret(getattr(settings, "MICROSOFT_OAUTH_CLIENT_SECRET", ""))
        redirect_default = solo.microsoft_oauth_redirect_uri or ""
        env_redirect = getattr(settings, "MICROSOFT_OAUTH_REDIRECT_URI", "")
    else:
        db_id = clean_secret(solo.google_oauth_client_id or "")
        db_secret = clean_secret(solo.google_oauth_client_secret or "")
        env_id = clean_secret(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", ""))
        env_secret = clean_secret(getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", ""))
        redirect_default = solo.google_oauth_redirect_uri or ""
        env_redirect = getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "")

    if db_id and db_secret:
        source = "appsettings"
        client_id, client_secret = db_id, db_secret
    elif env_id and env_secret:
        source = "env"
        client_id, client_secret = env_id, env_secret
    else:
        source = "none"
        client_id = _non_empty(db_id, env_id)
        client_secret = _non_empty(db_secret, env_secret)

    redirect_uri = _non_empty(redirect_uri_override, redirect_default, env_redirect)
    return OAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        source=source,
        provider=provider,
    )


def validate_oauth_config(*, provider: str | None = None, redirect_uri: str = "") -> list[str]:
    """Return human-readable validation errors before hitting the OAuth provider."""
    provider = _normalize_provider(provider)
    cfg = get_oauth_config(provider=provider, redirect_uri_override=redirect_uri)
    errors: list[str] = []
    if not cfg.client_id:
        errors.append("Client ID is missing.")
    elif " " in cfg.client_id or "\n" in cfg.client_id:
        errors.append("Client ID contains whitespace — paste only the ID string.")
    elif provider == SystemEnums.CalendarProvider.GOOGLE and not cfg.client_id.endswith(
        ".apps.googleusercontent.com"
    ):
        errors.append(
            "Client ID must end with .apps.googleusercontent.com. "
            "In Google Cloud, create an OAuth client of type Web application "
            "(not Desktop or API key)."
        )
    if not cfg.client_secret:
        errors.append("Client secret is missing.")
    elif " " in cfg.client_secret or "\n" in cfg.client_secret:
        errors.append("Client secret contains whitespace — paste only the secret string.")
    if cfg.client_id and cfg.client_secret and cfg.client_id == cfg.client_secret:
        errors.append("Client ID and secret are identical — check you pasted each into the correct field.")
    if not redirect_uri and not cfg.redirect_uri:
        errors.append("Redirect URI could not be determined.")
    return errors


def oauth_client_id_hint(*, provider: str | None = None, redirect_uri: str = "") -> str:
    """Masked client id for UI verification."""
    client_id = get_oauth_config(provider=provider, redirect_uri_override=redirect_uri).client_id
    if not client_id:
        return ""
    if provider == SystemEnums.CalendarProvider.MICROSOFT:
        if len(client_id) <= 16:
            return client_id
        return f"{client_id[:8]}…{client_id[-4:]}"
    if len(client_id) <= 24:
        return client_id
    return f"{client_id[:12]}…{client_id[-20:]}"


def oauth_configured(*, provider: str | None = None, redirect_uri: str = "") -> bool:
    """True when client id + secret are available and pass basic validation."""
    cfg = get_oauth_config(provider=provider, redirect_uri_override=redirect_uri)
    return bool(cfg.client_id and cfg.client_secret and not validate_oauth_config(
        provider=provider, redirect_uri=redirect_uri
    ))


def oauth_setup_message(*, provider: str | None = None, redirect_uri: str = "") -> str:
    """Human-readable setup hint for the Planner calendar panel."""
    provider = _normalize_provider(provider)
    errors = validate_oauth_config(provider=provider, redirect_uri=redirect_uri)
    if errors:
        return " ".join(errors)
    cfg = get_oauth_config(provider=provider, redirect_uri_override=redirect_uri)
    label = "Google" if provider == SystemEnums.CalendarProvider.GOOGLE else "Microsoft"
    settings_anchor = (
        "#google-calendar-oauth"
        if provider == SystemEnums.CalendarProvider.GOOGLE
        else "#microsoft-calendar-oauth"
    )
    env_prefix = "GOOGLE_OAUTH" if provider == SystemEnums.CalendarProvider.GOOGLE else "MICROSOFT_OAUTH"
    if not cfg.client_id or not cfg.client_secret:
        return (
            f"Add {label} OAuth client ID and secret in Settings → {label} Calendar "
            f"(or set {env_prefix}_* in .env). "
            "App Settings values override .env when both are set."
        )
    if not cfg.redirect_uri:
        return (
            "OAuth client ready — Connect will use this site URL as the redirect. "
            f"Register that exact URI in the {label} app registration."
        )
    return f"OAuth client ready — use Connect to authorize {label} Calendar."
