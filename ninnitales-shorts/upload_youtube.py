"""
upload_youtube.py — upload a stitched Short to the NinniTales channel.

Standalone (no dependency on the AssuredReferral package). Reuses the same OAuth
refresh-token → access-token flow. Credentials come from env vars matching the
output of get_youtube_token.py:

    YOUTUBE_CLIENT_ID_NINNITALES
    YOUTUBE_CLIENT_SECRET_NINNITALES
    YOUTUBE_REFRESH_TOKEN_NINNITALES
    YOUTUBE_CHANNEL_ID_NINNITALES   (optional, informational)

It falls back to the un-suffixed YOUTUBE_* names if the _NINNITALES ones are unset.

Scheduling: pass publish_at (RFC3339 UTC, e.g. "2026-06-18T14:00:00Z") to upload
privately now and have YouTube flip it public at that time. Omit for immediate
public.
"""

import os
from pathlib import Path

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def _env(name: str) -> str | None:
    return os.environ.get(f"{name}_NINNITALES") or os.environ.get(name)


def _credentials() -> dict:
    return {
        "client_id": _env("YOUTUBE_CLIENT_ID"),
        "client_secret": _env("YOUTUBE_CLIENT_SECRET"),
        "refresh_token": _env("YOUTUBE_REFRESH_TOKEN"),
    }


def _access_token(creds: dict) -> str:
    resp = requests.post(TOKEN_URL, data={
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def upload(video_path: Path, title: str, description: str,
           tags: list[str] | None = None, publish_at: str | None = None) -> dict:
    """Upload `video_path` as a Short. Returns {video_id, url} or {error}."""
    video_path = Path(video_path)
    creds = _credentials()
    if not creds.get("refresh_token"):
        return {"error": "YOUTUBE_REFRESH_TOKEN(_NINNITALES) not set — run get_youtube_token.py"}

    try:
        token = _access_token(creds)
    except Exception as e:
        return {"error": f"token refresh failed: {e}"}

    status = {
        "selfDeclaredMadeForKids": False,
        "privacyStatus": "private" if publish_at else "public",
    }
    if publish_at:
        status["publishAt"] = publish_at

    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags or ["bedtime stories", "parenting", "kids", "toddler", "ninnitales"],
            "categoryId": "24",  # Entertainment
            "defaultLanguage": "en",
        },
        "status": status,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(video_path.stat().st_size),
    }
    init = requests.post(
        f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status",
        headers=headers, json=metadata, timeout=30,
    )
    init.raise_for_status()
    session_url = init.headers["Location"]

    with open(video_path, "rb") as f:
        put = requests.put(session_url, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "video/mp4",
        }, data=f, timeout=600)
    put.raise_for_status()

    vid = put.json().get("id", "unknown")
    url = f"https://youtube.com/shorts/{vid}"
    when = f"scheduled for {publish_at}" if publish_at else "public now"
    print(f"  ✅ uploaded ({when}): {url}")
    return {"status": "uploaded", "video_id": vid, "url": url}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Upload a Short to NinniTales.")
    ap.add_argument("video", type=Path)
    ap.add_argument("--title", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--publish-at", default=None,
                    help="RFC3339 UTC, e.g. 2026-06-18T14:00:00Z (omit = public now)")
    args = ap.parse_args()

    result = upload(
        args.video, args.title, args.description,
        tags=[t.strip() for t in args.tags.split(",") if t.strip()] or None,
        publish_at=args.publish_at,
    )
    if "error" in result:
        raise SystemExit(f"❌ {result['error']}")
