"""ledger.py — the record of every Short we publish, and what it earned.

Each upload appends one row. A day later analyze.py fills in the stats (views,
likes, comments, and how many of those views came from SEARCH vs the feed). Those
finalized rows are what run_pipeline reads to double down on winning keyword themes.

The file is plain JSON and is intentionally COMMITTED (like state.json) so the
GitHub Actions cron carries history across runs.

Row shape:
  {
    "video_id":  "abc123",
    "platform":  "youtube",
    "title":     "How to get your toddler to sleep fast 😴",
    "theme":     "sleep_fast",          # keyword bucket (for attribution)
    "url":       "https://youtube.com/shorts/abc123",
    "posted_at": "2026-06-20T23:00:00Z",
    # filled in by analyze.py once the video is >= ~24h old:
    "views": 1500, "likes": 40, "comments": 6,
    "search_views": 1200, "search_pct": 0.80,
    "measured_at": "2026-06-22T02:00:00Z",
    "finalized": true
  }
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = Path(__file__).parent / "ledger.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    try:
        return json.loads(LEDGER_PATH.read_text())
    except json.JSONDecodeError:
        return []


def save(rows: list[dict]) -> None:
    LEDGER_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False))


def log_upload(video_id: str, title: str, theme: str, url: str,
               platform: str = "youtube", status: str = "posted",
               publish_at: str | None = None, source: str = "generated",
               fmt: str | None = None, account_id: str | None = None,
               product: str | None = None, niche: str | None = None) -> None:
    """Append a freshly published post. Idempotent on (platform, video_id).

    status: "posted" (live now) or "scheduled" (private, publishAt set — awaiting
    its slot, vetoable from Telegram). posted_at is the SCHEDULED publish time when
    known, else now, so analyze.py's 24h clock starts when the post actually goes live.
    source: "generated" | "scraped" | "carousel" — the content type.

    The multi-dimensional fields (fmt/account_id/product/niche) let analyze.py attribute
    performance per (niche, format, platform) and per account, not just per theme. They
    default to None so older single-product callers keep working unchanged. `video_id`
    stays the canonical post id (works for any platform's media/post id).
    """
    rows = load()
    if any(r.get("video_id") == video_id and r.get("platform") == platform
           for r in rows):
        return
    row = {
        "video_id": video_id,
        "platform": platform,
        "title": title,
        "theme": theme or "untagged",
        "source": source,
        "url": url,
        "status": status,
        "posted_at": publish_at or _now(),
        "finalized": False,
    }
    # Only attach the new dimensions when supplied (keeps legacy rows clean).
    for k, v in {"format": fmt, "account_id": account_id, "product": product,
                 "niche": niche}.items():
        if v is not None:
            row[k] = v
    rows.append(row)
    save(rows)
    print(f"  📒 ledger: logged {video_id} ({source}, theme={theme or 'untagged'}, "
          f"{status}{f', {fmt}@{account_id}' if fmt else ''})")


def update(video_id: str, platform: str = "youtube", **stats) -> None:
    """Merge measured stats into a row and stamp measured_at."""
    rows = load()
    for r in rows:
        if r.get("video_id") == video_id and r.get("platform") == platform:
            r.update(stats)
            r["measured_at"] = _now()
            break
    save(rows)


def pending(min_age_hours: float = 24.0, platform: str = "youtube") -> list[dict]:
    """Rows old enough to measure that aren't finalized yet."""
    out = []
    now = datetime.now(timezone.utc)
    for r in load():
        if r.get("platform") != platform or r.get("finalized"):
            continue
        if r.get("status") == "vetoed":  # cancelled before going live
            continue
        try:
            posted = datetime.strptime(r["posted_at"], "%Y-%m-%dT%H:%M:%SZ") \
                .replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if (now - posted).total_seconds() >= min_age_hours * 3600:
            out.append(r)
    return out
