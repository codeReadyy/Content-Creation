"""oauth/meta.py — the Instagram connect flow via "Instagram API with Instagram login".

Business/Creator accounts log in with their OWN Instagram credentials — no Facebook
Page, no /me/accounts dance. The flow:
  1. Instagram OAuth → short-lived token + the IG user id.
  2. Exchange it for a LONG-LIVED token (~60 days).
  3. (optional) read username for confirmation.

We store the long-lived token + the IG user id under the account's suffix — exactly the
names publishers/instagram.py reads (INSTAGRAM_ACCESS_TOKEN_* / _BUSINESS_ACCOUNT_ID_*).
The IG user id IS the publishing target on the graph.instagram.com host. Long-lived
tokens expire in ~60 days, so the UI exposes a re-connect/refresh action.

Note: this API requires an HTTPS redirect URI (config.USE_HTTPS).
"""

from __future__ import annotations

import urllib.parse

import requests

import config

AUTHORIZE = "https://www.instagram.com/oauth/authorize"
TOKEN = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"


def auth_url(state: str) -> str:
    return f"{AUTHORIZE}?" + urllib.parse.urlencode({
        "client_id": config.INSTAGRAM_APP_ID,
        "redirect_uri": config.INSTAGRAM_REDIRECT,
        "response_type": "code",
        "scope": config.INSTAGRAM_SCOPES,
        "state": state,
    })


def exchange_code(code: str) -> tuple[str, str]:
    """Authorization code → (short-lived token, ig_user_id)."""
    r = requests.post(TOKEN, data={
        "client_id": config.INSTAGRAM_APP_ID,
        "client_secret": config.INSTAGRAM_APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": config.INSTAGRAM_REDIRECT,
        "code": code,
    }, timeout=30)
    if not r.ok:
        raise RuntimeError(f"Instagram token exchange failed ({r.status_code}): {r.text[:400]}")
    data = r.json()
    # Older responses nest under data[0]; newer return flat. Handle both.
    if isinstance(data.get("data"), list) and data["data"]:
        data = data["data"][0]
    return data["access_token"], str(data.get("user_id", ""))


def long_lived(short_token: str) -> tuple[str, int]:
    """Short-lived token → (long-lived token, expires_in seconds ~5.2M = 60d)."""
    r = requests.get(f"{GRAPH}/access_token", params={
        "grant_type": "ig_exchange_token",
        "client_secret": config.INSTAGRAM_APP_SECRET,
        "access_token": short_token,
    }, timeout=30)
    if not r.ok:
        raise RuntimeError(f"long-lived token exchange failed ({r.status_code}): {r.text[:400]}")
    data = r.json()
    return data["access_token"], int(data.get("expires_in", 0))


def refresh(long_token: str) -> tuple[str, int]:
    """Re-extend a long-lived token before it expires → (token, expires_in)."""
    r = requests.get(f"{GRAPH}/refresh_access_token", params={
        "grant_type": "ig_refresh_token",
        "access_token": long_token,
    }, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["access_token"], int(data.get("expires_in", 0))


def identity(token: str) -> tuple[str, str]:
    """(ig_user_id, username) for the connected account, or ('', '')."""
    r = requests.get(f"{GRAPH}/me",
                     params={"fields": "user_id,username", "access_token": token},
                     timeout=30)
    if not r.ok:
        return "", ""
    d = r.json()
    return str(d.get("user_id", "")), d.get("username", "")
