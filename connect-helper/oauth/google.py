"""oauth/google.py — the YouTube/Google connect flow (standalone).

Same OAuth 2.0 authorization-code flow proven in ninnitales-shorts/get_youtube_token.py,
reimplemented here so the helper stays decoupled. We ask for offline access + a forced
consent so Google returns a long-lived refresh_token, then read the channel identity so
the UI can confirm WHICH channel was linked before saving.
"""

from __future__ import annotations

import urllib.parse

import requests

import config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


def auth_url(state: str) -> str:
    return f"{AUTH_URL}?" + urllib.parse.urlencode({
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT,
        "response_type": "code",
        "scope": config.GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",          # force a fresh refresh_token
        "state": state,
    })


def exchange_code(code: str) -> dict:
    """Authorization code → tokens. Returns {refresh_token, access_token, ...}."""
    r = requests.post(TOKEN_URL, data={
        "code": code,
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": config.GOOGLE_REDIRECT,
        "grant_type": "authorization_code",
    }, timeout=30)
    r.raise_for_status()
    return r.json()


def channel_identity(access_token: str) -> tuple[str, str]:
    """(channel_id, channel_title) for the authorized account, or ('', '')."""
    r = requests.get(CHANNELS_URL, params={"part": "snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    if not r.ok or not r.json().get("items"):
        return "", ""
    item = r.json()["items"][0]
    return item["id"], item["snippet"]["title"]


def access_from_refresh(refresh_token: str) -> str | None:
    """Mint an access token from a stored refresh token (used by status checks)."""
    r = requests.post(TOKEN_URL, data={
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=30)
    return r.json().get("access_token") if r.ok else None
