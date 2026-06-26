"""publishers/tiktok.py — TikTok seam (INERT, deferred).

Wired into the registry so accounts.yml can reference TikTok and the orchestrator
routes to it, but publishing isn't implemented yet. Two things must land first:

  1. Non-India posting infra — TikTok is banned in India, so the upload must originate
     from a non-India IP (a proxy or a small cloud server / runner).
  2. TikTok Content Posting API access — app registration + review for direct posting.

When ready, implement publish() against the Content Posting API (init upload → PUT the
video → publish), resolving creds by account.creds_env like the other publishers.
"""

from __future__ import annotations

from core.models import VIDEO, Account, Asset, PostCopy
from publishers.base import register


class TikTokPublisher:
    platform = "tiktok"
    accepts = {VIDEO}

    def publish(self, asset: Asset, copy: PostCopy, account: Account,
                publish_at: str | None = None) -> dict:
        return {"error": "tiktok publishing not implemented yet "
                         "(needs non-India infra + Content Posting API access)"}


register(TikTokPublisher())
