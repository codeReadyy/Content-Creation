"""publishers/youtube.py — post a VIDEO Asset as a YouTube Short.

Thin Publisher adapter over upload_youtube.upload(); credentials are resolved per
account via account.creds_env (YOUTUBE_*_<creds_env>), so multiple YouTube accounts
are just different suffixes.
"""

from __future__ import annotations

import upload_youtube
from core.models import VIDEO, Account, Asset, PostCopy
from publishers.base import register


class YouTubePublisher:
    platform = "youtube"
    accepts = {VIDEO}

    def publish(self, asset: Asset, copy: PostCopy, account: Account,
                publish_at: str | None = None) -> dict:
        if asset.kind not in self.accepts:
            return {"error": f"youtube can't post asset kind '{asset.kind}'"}
        res = upload_youtube.upload(
            asset.path, copy.title, copy.caption,
            tags=copy.tags or None, publish_at=publish_at,
            creds_env=account.creds_env,
        )
        if "error" in res:
            return {"error": res["error"]}
        return {"post_id": res["video_id"], "url": res["url"]}


register(YouTubePublisher())
