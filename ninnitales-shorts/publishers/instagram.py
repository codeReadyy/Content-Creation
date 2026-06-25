"""publishers/instagram.py — post a VIDEO (Reel) or CAROUSEL to Instagram.

Instagram Graph API content publishing is a 3-step dance: create a media CONTAINER
(by URL), wait for it to finish processing, then PUBLISH it. Media is fetched by URL,
so we host each file via hosting.public_url() (a GitHub release asset) first.

Credentials per account by suffix (account.creds_env), e.g. NINNITALES_IG →
  INSTAGRAM_ACCESS_TOKEN_NINNITALES_IG   (long-lived token)
  INSTAGRAM_BUSINESS_ACCOUNT_ID_NINNITALES_IG

Note: this API has NO native scheduling for content publishing, so `publish_at` is
ignored and the post goes live immediately when the run executes. To honour per-slot
timing for IG, trigger the run at the slot time (a later refinement); for now the IG
account is disabled in accounts.yml until creds + a hosting repo are in place.
"""

from __future__ import annotations

import os
import time

import requests

import hosting
from core.models import CAROUSEL, VIDEO, Account, Asset, PostCopy
from publishers.base import register

GRAPH = "https://graph.facebook.com/v21.0"


def _creds(suffix: str) -> dict:
    def env(name):
        return os.environ.get(f"{name}_{suffix}") or os.environ.get(name)
    return {"token": env("INSTAGRAM_ACCESS_TOKEN"),
            "ig_id": env("INSTAGRAM_BUSINESS_ACCOUNT_ID")}


def _caption(copy: PostCopy) -> str:
    tags = " ".join(copy.hashtags)
    return f"{copy.caption}\n\n{tags}".strip() if tags else copy.caption


class InstagramPublisher:
    platform = "instagram"
    accepts = {VIDEO, CAROUSEL}

    def publish(self, asset: Asset, copy: PostCopy, account: Account,
                publish_at: str | None = None) -> dict:
        creds = _creds(account.creds_env)
        if not creds["token"] or not creds["ig_id"]:
            return {"error": f"INSTAGRAM_*_{account.creds_env} not set"}
        try:
            if asset.kind == VIDEO:
                container = self._reel_container(asset, copy, creds)
            elif asset.kind == CAROUSEL:
                container = self._carousel_container(asset, copy, creds)
            else:
                return {"error": f"instagram can't post asset kind '{asset.kind}'"}
            self._wait_ready(container, creds)
            post_id = self._publish(container, creds)
        except Exception as e:
            return {"error": f"instagram publish failed: {e}"}
        kind_path = "reel" if asset.kind == VIDEO else "p"
        return {"post_id": post_id, "url": f"https://www.instagram.com/{kind_path}/{post_id}/"}

    # ── Graph API steps ──────────────────────────────────────────────────────
    def _create(self, creds: dict, **params) -> str:
        params["access_token"] = creds["token"]
        r = requests.post(f"{GRAPH}/{creds['ig_id']}/media", data=params, timeout=120)
        r.raise_for_status()
        return r.json()["id"]

    def _reel_container(self, asset: Asset, copy: PostCopy, creds: dict) -> str:
        url = hosting.public_url(asset.path)
        return self._create(creds, media_type="REELS", video_url=url,
                            caption=_caption(copy), share_to_feed="true")

    def _carousel_container(self, asset: Asset, copy: PostCopy, creds: dict) -> str:
        children = []
        for img in asset.paths:
            children.append(self._create(creds, image_url=hosting.public_url(img),
                                         is_carousel_item="true"))
        return self._create(creds, media_type="CAROUSEL",
                            children=",".join(children), caption=_caption(copy))

    def _wait_ready(self, container: str, creds: dict, tries: int = 30) -> None:
        """Poll container status until FINISHED (Reels need transcoding time)."""
        for _ in range(tries):
            r = requests.get(f"{GRAPH}/{container}",
                             params={"fields": "status_code", "access_token": creds["token"]},
                             timeout=30)
            r.raise_for_status()
            status = r.json().get("status_code")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise RuntimeError("media container processing failed")
            time.sleep(5)
        raise RuntimeError("media container not ready after polling")

    def _publish(self, container: str, creds: dict) -> str:
        r = requests.post(f"{GRAPH}/{creds['ig_id']}/media_publish",
                          data={"creation_id": container, "access_token": creds["token"]},
                          timeout=60)
        r.raise_for_status()
        return r.json()["id"]


register(InstagramPublisher())
