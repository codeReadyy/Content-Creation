"""oauth/pinterest.py — the Pinterest connect flow (standalone).

Standard OAuth 2.0 authorization-code flow against the Pinterest API v5. We ask for the
boards/pins read+write scopes (+ user_accounts:read for the identity confirmation) and
exchange the code for an ACCESS token + a long-lived REFRESH token. We store the refresh
token (publishers/pinterest.py mints a fresh access token from it each run, since Pinterest
access tokens last ~1h). The token endpoint authenticates the app via HTTP Basic.

Pinterest requires an HTTPS redirect URI, so the helper's default self-signed HTTPS works.
"""

from __future__ import annotations

import base64
import urllib.parse

import requests

import config

AUTHORIZE = "https://www.pinterest.com/oauth/"
TOKEN = "https://api.pinterest.com/v5/oauth/token"
API = "https://api.pinterest.com/v5"


def auth_url(state: str) -> str:
    return f"{AUTHORIZE}?" + urllib.parse.urlencode({
        "client_id": config.PINTEREST_APP_ID,
        "redirect_uri": config.PINTEREST_REDIRECT,
        "response_type": "code",
        "scope": config.PINTEREST_SCOPES,
        "state": state,
    })


def _basic() -> str:
    raw = f"{config.PINTEREST_APP_ID}:{config.PINTEREST_APP_SECRET}".encode()
    return base64.b64encode(raw).decode()


def exchange_code(code: str) -> dict:
    """Authorization code → {access_token, refresh_token, ...} (app via HTTP Basic)."""
    r = requests.post(TOKEN, headers={
        "Authorization": f"Basic {_basic()}",
        "Content-Type": "application/x-www-form-urlencoded",
    }, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.PINTEREST_REDIRECT,
    }, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Pinterest token exchange failed ({r.status_code}): {r.text[:400]}")
    return r.json()


def identity(access_token: str) -> str:
    """The connected account's username, or '' if it can't be read."""
    r = requests.get(f"{API}/user_account",
                     headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    return r.json().get("username", "") if r.ok else ""
