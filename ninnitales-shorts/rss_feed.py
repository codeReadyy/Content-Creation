"""rss_feed.py — Pinterest RSS auto-publish backend (the no-API-approval route).

Pinterest's Standard API access keeps getting denied, but business accounts can
AUTO-PUBLISH pins from RSS feeds natively (Settings → Bulk create Pins → Auto-publish;
up to 200 pins/day, ingested within 24-48h, no developer approval needed). So instead
of POSTing to the Pinterest API, the pin pipeline appends items to per-board RSS feeds
hosted in the public MEDIA_REPO (the same repo that hosts Instagram media), and
Pinterest pulls them.

One feed per board (Pinterest maps feed → board 1:1), file layout in the media repo:
  {MEDIA_PREFIX}/pinterest/{board-slug}.json   ← item state (source of truth)
  {MEDIA_PREFIX}/pinterest/{board-slug}.xml    ← the RSS 2.0 feed Pinterest ingests

ONE-TIME manual setup (per board): claim the site (niche waitlist_url domain) on the
Pinterest business profile, then paste each feed's raw URL under Auto-publish and pick
its board. `python rss_feed.py` prints the feed URLs to paste.

Files are committed to the media repo's default branch via the GitHub Contents API
(feeds are tiny text — well under the API's ~1 MB cap; pin IMAGES still go through
hosting.public_url release assets, which handle big files)."""

from __future__ import annotations

import base64
import html
import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime

import requests

import hosting

API = "https://api.github.com"
MAX_ITEMS = 50          # Pinterest only needs NEW items; keep feeds small


def _slug(board: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", board.lower())).strip("-")


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _default_branch(repo: str, token: str) -> str:
    r = requests.get(f"{API}/repos/{repo}", headers=_headers(token), timeout=30)
    r.raise_for_status()
    return r.json().get("default_branch", "main")


def _get_file(repo: str, token: str, path: str) -> tuple[str | None, str | None]:
    """(decoded text, blob sha) — (None, None) when the file doesn't exist yet."""
    r = requests.get(f"{API}/repos/{repo}/contents/{path}",
                     headers=_headers(token), timeout=30)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    j = r.json()
    return base64.b64decode(j["content"]).decode(), j["sha"]


def _put_file(repo: str, token: str, path: str, text: str, sha: str | None,
              message: str) -> None:
    body = {"message": message,
            "content": base64.b64encode(text.encode()).decode()}
    if sha:
        body["sha"] = sha
    r = requests.put(f"{API}/repos/{repo}/contents/{path}",
                     headers=_headers(token), json=body, timeout=60)
    r.raise_for_status()


def _rss(board: str, site_link: str, items: list[dict]) -> str:
    """Render RSS 2.0. Image via <enclosure> AND an <img> in the description CDATA —
    Pinterest reads either, so both is the safe combination."""
    e = html.escape
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0">', "<channel>",
           f"<title>{e(board)}</title>",
           f"<link>{e(site_link)}</link>",
           f"<description>{e(board)} — new ideas every day</description>"]
    for it in items:
        desc = (f'<img src="{e(it["image"])}" alt="{e(it["title"])}"/>'
                f'<p>{e(it["description"])}</p>')
        out += ["<item>",
                f"<title>{e(it['title'])}</title>",
                f"<link>{e(it['link'])}</link>",
                f"<guid isPermaLink=\"false\">{e(it['guid'])}</guid>",
                f"<pubDate>{e(it['pub_date'])}</pubDate>",
                f"<description><![CDATA[{desc}]]></description>",
                f"<enclosure url=\"{e(it['image'])}\" type=\"image/png\" length=\"0\"/>",
                "</item>"]
    out += ["</channel>", "</rss>"]
    return "\n".join(out)


def feed_paths(board: str) -> tuple[str, str]:
    base = f"{hosting._project()}/pinterest/{_slug(board)}"
    return f"{base}.json", f"{base}.xml"


def feed_url(board: str, repo: str | None = None, branch: str = "main") -> str:
    if repo is None:
        repo, _ = hosting._repo_token()
    _, xml_path = feed_paths(board)
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{xml_path}"


def add_pin(board: str, title: str, description: str, image_url: str,
            link: str, site_link: str, guid: str) -> str:
    """Append one pin to the board's feed in the media repo. Returns the feed's raw URL
    (what gets pasted into Pinterest's Auto-publish once, and logged in the ledger)."""
    repo, token = hosting._repo_token()
    branch = _default_branch(repo, token)
    json_path, xml_path = feed_paths(board)

    state_text, state_sha = _get_file(repo, token, json_path)
    try:
        items = json.loads(state_text) if state_text else []
    except json.JSONDecodeError:
        items = []
    items.insert(0, {
        "guid": guid, "title": title, "description": description,
        "image": image_url, "link": link,
        "pub_date": format_datetime(datetime.now(timezone.utc)),
    })
    items = items[:MAX_ITEMS]

    msg = f"pin: {title[:60]} [{_slug(board)}]"
    _put_file(repo, token, json_path, json.dumps(items, indent=1, ensure_ascii=False),
              state_sha, msg)
    _, xml_sha = _get_file(repo, token, xml_path)
    _put_file(repo, token, xml_path, _rss(board, site_link, items), xml_sha, msg)
    return feed_url(board, repo, branch)


def main() -> None:
    """Print the feed URL per board — paste each into Pinterest → Settings →
    Bulk create Pins → Auto-publish (requires the claimed website)."""
    import run_pipeline
    run_pipeline._load_env()
    from core import config
    niche = config.load_niche("toddler_sleep")
    boards = niche.extra.get("pinterest_boards") or []
    try:
        repo, token = hosting._repo_token()
        branch = _default_branch(repo, token)
    except Exception:
        repo, branch = "<MEDIA_REPO>", "main"
    print("Paste each URL into Pinterest → Settings → Bulk create Pins → Auto-publish,")
    print("and pick the matching board (needs the claimed website on the profile):\n")
    for b in boards:
        print(f"  {b:<28} → {feed_url(b, repo, branch)}")


if __name__ == "__main__":
    main()
