"""oauth/meta.py — the Instagram/Facebook connect flow (standalone).

Instagram content publishing is gated behind Facebook Login + the Graph API. The dance:
  1. Facebook OAuth → short-lived user token.
  2. Exchange it for a LONG-LIVED user token (~60 days).
  3. List the user's Pages; each Page may have a linked IG Business account.
  4. Resolve the IG business-account id + username for the chosen Page.

We store the long-lived USER token (works for content publishing on the linked IG
account) + the IG business-account id — exactly the names publishers/instagram.py reads.
Long-lived tokens expire in ~60 days, so the UI exposes a re-connect/refresh action.
"""

from __future__ import annotations

import urllib.parse

import requests

import config

DIALOG = "https://www.facebook.com/v21.0/dialog/oauth"
GRAPH = config.GRAPH


def auth_url(state: str) -> str:
    return f"{DIALOG}?" + urllib.parse.urlencode({
        "client_id": config.META_APP_ID,
        "redirect_uri": config.META_REDIRECT,
        "response_type": "code",
        "scope": config.META_SCOPES,
        "state": state,
    })


def exchange_code(code: str) -> str:
    """Authorization code → short-lived user access token."""
    r = requests.get(f"{GRAPH}/oauth/access_token", params={
        "client_id": config.META_APP_ID,
        "client_secret": config.META_APP_SECRET,
        "redirect_uri": config.META_REDIRECT,
        "code": code,
    }, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def long_lived(short_token: str) -> tuple[str, int]:
    """Short-lived token → (long-lived token, expires_in seconds ~5.2M = 60d)."""
    r = requests.get(f"{GRAPH}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": config.META_APP_ID,
        "client_secret": config.META_APP_SECRET,
        "fb_exchange_token": short_token,
    }, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["access_token"], int(data.get("expires_in", 0))


def list_pages(token: str) -> list[dict]:
    """The user's Pages: [{id, name, access_token}, ...]."""
    r = requests.get(f"{GRAPH}/me/accounts",
                     params={"access_token": token, "fields": "id,name,access_token"},
                     timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def ig_account(page_id: str, token: str) -> tuple[str, str]:
    """(ig_business_account_id, username) linked to a Page, or ('', '')."""
    r = requests.get(f"{GRAPH}/{page_id}",
                     params={"fields": "instagram_business_account{id,username}",
                             "access_token": token}, timeout=30)
    if not r.ok:
        return "", ""
    ig = r.json().get("instagram_business_account") or {}
    return ig.get("id", ""), ig.get("username", "")


def discover_ig(token: str) -> list[dict]:
    """All IG business accounts reachable via the user's Pages.

    Returns [{page_id, page_name, ig_id, username}] — the UI picks one when there are
    several (most users have exactly one).
    """
    out = []
    for page in list_pages(token):
        ig_id, username = ig_account(page["id"], token)
        if ig_id:
            out.append({"page_id": page["id"], "page_name": page.get("name", ""),
                        "ig_id": ig_id, "username": username})
    return out


def token_expiry(token: str) -> str | None:
    """Human expiry from the debug endpoint (for the status view); None if unknown."""
    import datetime
    r = requests.get(f"{GRAPH}/debug_token",
                     params={"input_token": token,
                             "access_token": f"{config.META_APP_ID}|{config.META_APP_SECRET}"},
                     timeout=30)
    if not r.ok:
        return None
    ts = (r.json().get("data") or {}).get("data_access_expires_at") \
        or (r.json().get("data") or {}).get("expires_at")
    if not ts:
        return None
    return datetime.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
