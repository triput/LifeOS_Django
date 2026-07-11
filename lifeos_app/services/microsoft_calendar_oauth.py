# ==============================================================================
# File: lifeos_app/services/microsoft_calendar_oauth.py
# Description: Microsoft Graph calendar OAuth (ENG-CAL-MS)
# Component: Services / Calendar
# Version: 1.0 (Gold Master)
# Created: 2026-07-09
# Last Update: 2026-07-09
# ==============================================================================
"""OAuth2 PKCE helpers for Microsoft Graph Calendars.Read access."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

from lifeos_app.models import SystemEnums
from lifeos_app.services.calendar_config import get_oauth_config, oauth_configured
from lifeos_app.services.calendar_oauth import oauth_session_key, save_integration_credentials

MICROSOFT_AUTHORITY = "https://login.microsoftonline.com/common"
MICROSOFT_TOKEN_URL = f"{MICROSOFT_AUTHORITY}/oauth2/v2.0/token"
MICROSOFT_AUTHORIZE_URL = f"{MICROSOFT_AUTHORITY}/oauth2/v2.0/authorize"
MICROSOFT_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
MICROSOFT_CALENDAR_SCOPES = "Calendars.Read offline_access"


@dataclass(frozen=True)
class AuthorizationStart:
    """OAuth consent redirect URL plus PKCE verifier for the callback."""

    url: str
    code_verifier: str


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def start_authorization(state: str, *, redirect_uri: str) -> AuthorizationStart:
    """Build Microsoft consent URL with PKCE."""
    if not oauth_configured(provider=SystemEnums.CalendarProvider.MICROSOFT, redirect_uri=redirect_uri):
        raise ValueError("Microsoft OAuth client is not configured.")
    config = get_oauth_config(
        provider=SystemEnums.CalendarProvider.MICROSOFT,
        redirect_uri_override=redirect_uri,
    )
    code_verifier, code_challenge = _pkce_pair()
    params = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": MICROSOFT_CALENDAR_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "consent",
    }
    return AuthorizationStart(url=f"{MICROSOFT_AUTHORIZE_URL}?{urlencode(params)}", code_verifier=code_verifier)


def exchange_code(code: str, *, redirect_uri: str, code_verifier: str) -> dict:
    """Exchange authorization code for token JSON suitable for credentials_json."""
    if not code_verifier:
        raise ValueError("Missing PKCE code verifier — restart Connect from Planner.")
    config = get_oauth_config(
        provider=SystemEnums.CalendarProvider.MICROSOFT,
        redirect_uri_override=redirect_uri,
    )
    response = requests.post(
        MICROSOFT_TOKEN_URL,
        data={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
            "scope": MICROSOFT_CALENDAR_SCOPES,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise ValueError(response.text[:300])
    payload = response.json()
    return {
        "token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "token_uri": MICROSOFT_TOKEN_URL,
        "client_id": config.client_id,
        "scopes": (payload.get("scope") or MICROSOFT_CALENDAR_SCOPES).split(),
        "expires_in": payload.get("expires_in"),
    }


def fetch_owner_email(access_token: str) -> str:
    """Resolve mailbox / UPN for CalendarIntegration.user_email."""
    response = requests.get(
        f"{MICROSOFT_GRAPH_BASE}/me",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"$select": "mail,userPrincipalName"},
        timeout=30,
    )
    if response.status_code >= 400:
        return ""
    data = response.json()
    return (data.get("mail") or data.get("userPrincipalName") or "").strip()


def connect_microsoft_account(
    code: str,
    *,
    redirect_uri: str,
    code_verifier: str,
):
    """Exchange OAuth code, persist integration, and return the integration row."""
    credentials = exchange_code(code, redirect_uri=redirect_uri, code_verifier=code_verifier)
    user_email = fetch_owner_email(credentials.get("token") or "") or "owner@lifeos.local"
    return save_integration_credentials(
        credentials,
        user_email=user_email,
        provider=SystemEnums.CalendarProvider.MICROSOFT,
    )
