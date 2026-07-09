"""publishers/pinterest.py — post a single IMAGE as a Pinterest pin (API v5).

Pinterest is a SEARCH/evergreen surface: a pin = a 2:3 image + keyword title + keyword
description + a DESTINATION LINK (the point — it drives traffic for months). Publishing:
  1. mint an access token from the account's long-lived REFRESH token (Pinterest access
     tokens last ~1h, so we refresh every run — the YouTube pattern, not IG's 60d token);
  2. resolve the target board NAME -> board_id (create the board if it doesn't exist yet);
  3. create the pin with the image inline as base64 (no media hosting needed, so this
     repo can stay private — unlike Instagram which fetches media by URL).

Credentials per account by suffix (account.creds_env), e.g. NINNITALES ->
  PINTEREST_APP_ID_NINNITALES        (the Pinterest app id;     un-suffixed fallback ok)
  PINTEREST_APP_SECRET_NINNITALES    (the Pinterest app secret; un-suffixed fallback ok)
  PINTEREST_REFRESH_TOKEN_NINNITALES (long-lived refresh token; minted by connect-helper)

Pinterest has NO native publish scheduling on the standard API, so `publish_at` is
ignored and the pin goes live immediately — the cron slot time IS the post time (run with
`orchestrate.py --platform pinterest --now N`, like the Instagram path).

RSS MODE (`publish_via: rss` on the account in accounts.yml): Standard API access keeps
getting denied and Trial pins are sandbox-only (invisible to the public), so this mode
skips the API entirely — the image is hosted publicly (hosting.public_url) and an item is
appended to the board's RSS feed in the media repo (rss_feed.add_pin); Pinterest's native
Auto-publish then creates the real, public pin within 24-48h. Needs MEDIA_REPO +
MEDIA_REPO_TOKEN, no PINTEREST_* creds. One-time setup: `python rss_feed.py`.
"""

from __future__ import annotations

import base64
import os
import time

import requests

from core.models import IMAGE, Account, Asset, PostCopy
from publishers.base import register

API = "https://api.pinterest.com/v5"


def _raise_for_status(r) -> None:
    """Like raise_for_status, but include Pinterest's JSON message (its `code`/`message`
    explain the real cause — e.g. code 29 = the app is still on Trial access)."""
    if r.ok:
        return
    try:
        j = r.json()
        msg = f"{j.get('message', r.text[:300])} (code {j.get('code')})"
    except ValueError:
        msg = r.text[:300]
    if "trial access" in msg.lower():
        msg += " → request STANDARD access at developers.pinterest.com (App → Request access)."
    raise RuntimeError(f"HTTP {r.status_code}: {msg}")


def _env(name: str, suffix: str) -> str | None:
    return os.environ.get(f"{name}_{suffix}") or os.environ.get(name)


def _creds(suffix: str) -> dict:
    return {"app_id": _env("PINTEREST_APP_ID", suffix),
            "app_secret": _env("PINTEREST_APP_SECRET", suffix),
            "refresh": _env("PINTEREST_REFRESH_TOKEN", suffix)}


def access_token(creds: dict) -> str:
    """Exchange the long-lived refresh token for a short-lived access token (HTTP Basic)."""
    basic = base64.b64encode(
        f"{creds['app_id']}:{creds['app_secret']}".encode()).decode()
    r = requests.post(f"{API}/oauth/token",
                      headers={"Authorization": f"Basic {basic}",
                               "Content-Type": "application/x-www-form-urlencoded"},
                      data={"grant_type": "refresh_token",
                            "refresh_token": creds["refresh"]},
                      timeout=30)
    if not r.ok:
        raise RuntimeError(f"token refresh failed ({r.status_code}): {r.text[:300]}")
    return r.json()["access_token"]


class PinterestPublisher:
    platform = "pinterest"
    accepts = {IMAGE}

    def publish(self, asset: Asset, copy: PostCopy, account: Account,
                publish_at: str | None = None) -> dict:
        if account.extra.get("publish_via") == "rss":
            return self._publish_rss(asset, copy)
        creds = _creds(account.creds_env)
        if not all((creds["app_id"], creds["app_secret"], creds["refresh"])):
            return {"error": f"PINTEREST_*_{account.creds_env} not set "
                             "(app id/secret + refresh token)"}
        try:
            token = access_token(creds)
            board_id = self._board_id(token, asset.meta.get("board") or "Toddler Bedtime")
            pin_id = self._create_pin(token, board_id, asset, copy)
        except Exception as e:
            return {"error": f"pinterest publish failed: {e}"}
        return {"post_id": pin_id, "url": f"https://www.pinterest.com/pin/{pin_id}/"}

    # ── RSS auto-publish path (no API approval needed) ────────────────────────
    def _publish_rss(self, asset: Asset, copy: PostCopy) -> dict:
        import hosting
        import rss_feed
        try:
            image_url = hosting.public_url(asset.path)
            guid = f"pin-{int(time.time())}-{asset.theme}"
            base = asset.meta.get("link") or "https://ninnitales.com"
            sep = "&" if "?" in base else "?"
            # unique per-item link (same claimed domain) so Pinterest never dedupes items
            link = (f"{base}{sep}utm_source=pinterest&utm_medium=rss"
                    f"&utm_campaign={asset.theme}&p={guid}")
            url = rss_feed.add_pin(
                board=asset.meta.get("board") or "Toddler Bedtime",
                title=copy.title[:100], description=copy.caption[:800],
                image_url=image_url, link=link, site_link=base, guid=guid)
        except Exception as e:
            return {"error": f"pinterest rss publish failed: {e}"}
        return {"post_id": guid, "url": url}

    # ── v5 API steps ──────────────────────────────────────────────────────────
    def _board_id(self, token: str, name: str) -> str:
        h = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{API}/boards", headers=h,
                         params={"page_size": 100}, timeout=30)
        _raise_for_status(r)
        for b in r.json().get("items", []):
            if (b.get("name") or "").lower() == name.lower():
                return b["id"]
        # Not found → create it (public so pins are searchable).
        r = requests.post(f"{API}/boards", headers=h,
                          json={"name": name, "privacy": "PUBLIC"}, timeout=30)
        _raise_for_status(r)
        return r.json()["id"]

    def _create_pin(self, token: str, board_id: str, asset: Asset,
                    copy: PostCopy) -> str:
        with open(asset.path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        body = {
            "board_id": board_id,
            "title": copy.title[:100],
            "description": copy.caption[:800],
            "link": asset.meta.get("link"),
            "media_source": {"source_type": "image_base64",
                             "content_type": "image/png", "data": b64},
        }
        r = requests.post(f"{API}/pins",
                          headers={"Authorization": f"Bearer {token}"},
                          json=body, timeout=120)
        _raise_for_status(r)
        return r.json()["id"]


register(PinterestPublisher())
