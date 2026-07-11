# ==============================================================================
# File: lifeos_app/services/calendar_oauth.py
# Description: Google Calendar OAuth connect flow (ENG-CAL / P5-03)
# Component: Services / Calendar
# Version: 1.2 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-10
# ==============================================================================
"""OAuth2 helpers for Google Calendar (read-only or write when push enabled)."""

from __future__ import annotations

from dataclasses import dataclass

from google_auth_oauthlib.flow import Flow

from lifeos_app.models import CalendarIntegration
from lifeos_app.services.calendar_config import OAuthConfig, get_oauth_config, oauth_configured
from lifeos_app.services.calendar_sync import google_oauth_scopes


def oauth_session_key(provider: str, suffix: str) -> str:
    """Provider-scoped session keys so Google and Microsoft flows do not collide."""
    return f"lifeos_calendar_{provider}_{suffix}"


OAUTH_STATE_SESSION_KEY = oauth_session_key("google", "state")
OAUTH_REDIRECT_SESSION_KEY = oauth_session_key("google", "redirect")
OAUTH_CODE_VERIFIER_SESSION_KEY = oauth_session_key("google", "code_verifier")


@dataclass(frozen=True)
class AuthorizationStart:
    """OAuth consent redirect URL plus PKCE verifier for the callback."""

    url: str
    code_verifier: str


def _client_config(config: OAuthConfig) -> dict:
    if not config.redirect_uri:
        raise ValueError("OAuth redirect URI is required.")
    return {
        "web": {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [config.redirect_uri],
        }
    }


def build_oauth_flow(*, redirect_uri: str) -> Flow:
    """Create OAuth flow — readonly, or full calendar when push is enabled."""
    config = get_oauth_config(redirect_uri_override=redirect_uri)
    if not oauth_configured(redirect_uri=redirect_uri):
        raise ValueError("Google OAuth client is not configured.")
    config = OAuthConfig(
        client_id=config.client_id,
        client_secret=config.client_secret,
        redirect_uri=redirect_uri,
        source=config.source,
    )
    return Flow.from_client_config(
        _client_config(config),
        scopes=google_oauth_scopes(),
        redirect_uri=redirect_uri,
    )


def start_authorization(state: str, *, redirect_uri: str) -> AuthorizationStart:
    """
    Build Google consent URL and capture PKCE code_verifier for token exchange.

    google-auth-oauthlib enables PKCE by default; the verifier must be restored
    on callback or Google returns ``invalid_grant: Missing code verifier``.
    """
    flow = build_oauth_flow(redirect_uri=redirect_uri)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return AuthorizationStart(url=url, code_verifier=flow.code_verifier)


def authorization_url(state: str, *, redirect_uri: str) -> str:
    """Return Google OAuth consent URL (legacy helper — prefer start_authorization)."""
    return start_authorization(state, redirect_uri=redirect_uri).url


def exchange_code(code: str, *, redirect_uri: str, code_verifier: str) -> dict:
    """Exchange authorization code for token JSON suitable for credentials_json."""
    if not code_verifier:
        raise ValueError("Missing PKCE code verifier — restart Connect from Planner.")
    flow = build_oauth_flow(redirect_uri=redirect_uri)
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials
    config = get_oauth_config(redirect_uri_override=redirect_uri)
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": config.client_id,
        "scopes": list(creds.scopes or google_oauth_scopes()),
    }


def save_integration_credentials(
    credentials: dict,
    user_email: str = "",
    *,
    provider: str | None = None,
) -> CalendarIntegration:
    """Persist OAuth tokens on CalendarIntegration."""
    from lifeos_app.models import SystemEnums

    provider = provider or SystemEnums.CalendarProvider.GOOGLE
    integration, _ = CalendarIntegration.objects.update_or_create(
        provider=provider,
        user_email=user_email or "owner@lifeos.local",
        defaults={
            "credentials_json": credentials,
            "sync_enabled": True,
            "last_sync_error": "",
        },
    )
    return integration
