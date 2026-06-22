"""publish.py — platform-agnostic publishing seam.

daily.py publishes through this instead of calling a platform directly, so adding
Instagram / TikTok later is additive (a new branch here + creds) rather than a
rewrite. Phase 1 = YouTube only.

Returns {platform: result}. The "youtube" result carries {video_id, url} (used for
the Telegram veto + ledger) or {error}.
"""

import upload_youtube

PLATFORMS = ("youtube",)  # extend with "instagram", "tiktok" in later phases


def publish(video_path: str, title: str, description: str,
            tags: list[str] | None = None, publish_at: str | None = None,
            platforms: tuple[str, ...] = ("youtube",)) -> dict:
    results: dict = {}
    if "youtube" in platforms:
        results["youtube"] = upload_youtube.upload(
            video_path, title, description, tags=tags, publish_at=publish_at)
    # Phase 2: if "instagram" in platforms: results["instagram"] = instagram_reels.publish(...)
    # Phase 3: if "tiktok" in platforms:   results["tiktok"]   = tiktok.publish(...)
    return results
