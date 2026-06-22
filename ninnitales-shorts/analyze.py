"""analyze.py — measure each Short ~24h after posting, then pick the winners.

For every ledger row that's >= 24h old and not yet finalized:
  • YouTube Data API  → views / likes / comments       (works with current auth)
  • YouTube Analytics → how many of those views came from SEARCH vs the feed
                        (needs the yt-analytics.readonly scope — re-mint the token
                         with get_youtube_token.py; until then search data is skipped)

It writes the numbers back into the ledger, then aggregates by keyword `theme`
into analytics/winners.json. run_pipeline reads that file and biases future titles
toward the themes that earned the most SEARCH-driven views — doubling down on what
parents actually click.

Usage:
    python analyze.py              # measure + print report + write winners.json
    python analyze.py --min-age 24 # only measure videos at least N hours old
    python analyze.py --report     # just print the standings, don't re-measure
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone

import requests

import run_pipeline
import upload_youtube
from analytics import ledger

DATA_API = "https://www.googleapis.com/youtube/v3/videos"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
WINNERS_PATH = ledger.LEDGER_PATH.parent / "winners.json"


def _stats(token: str, video_id: str) -> dict:
    """Public counters via the Data API: views / likes / comments."""
    r = requests.get(DATA_API, params={"part": "statistics", "id": video_id},
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return {}
    s = items[0].get("statistics", {})
    return {
        "views": int(s.get("viewCount", 0)),
        "likes": int(s.get("likeCount", 0)),
        "comments": int(s.get("commentCount", 0)),
    }


def _search_views(token: str, video_id: str, posted_at: str) -> int | None:
    """Views that came from YouTube SEARCH, via the Analytics API.

    Returns None (and prints a one-time hint) if the token lacks the analytics
    scope — the rest of the pipeline still works on total views until you re-auth.
    """
    start = posted_at[:10]
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        r = requests.get(ANALYTICS_API, params={
            "ids": "channel==MINE",
            "startDate": start,
            "endDate": end,
            "metrics": "views",
            "dimensions": "insightTrafficSourceType",
            "filters": f"video=={video_id}",
        }, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except requests.RequestException:
        return None
    if r.status_code in (401, 403):
        body = r.text.lower()
        if "has not been used" in body or "is disabled" in body:
            print("  ⚠️  YouTube Analytics API is disabled for this Cloud project. "
                  "Enable it once at console.cloud.google.com → APIs & Services → "
                  "Library → 'YouTube Analytics API' → Enable.")
        else:
            print("  ⚠️  no analytics scope — re-mint: python get_youtube_token.py "
                  "(grants yt-analytics.readonly).")
        return None
    if not r.ok:
        return None
    for source, views in r.json().get("rows", []) or []:
        if source == "YT_SEARCH":
            return int(views)
    return 0  # query worked, just zero search views so far


def measure(min_age_hours: float) -> int:
    """Fill in stats for due videos. Returns how many were finalized."""
    run_pipeline._load_env()
    due = ledger.pending(min_age_hours=min_age_hours)
    if not due:
        print("No videos due for measurement.")
        return 0
    token = upload_youtube._access_token(upload_youtube._credentials())
    analytics_ok = True
    done = 0
    for row in due:
        vid = row["video_id"]
        try:
            st = _stats(token, vid)
        except Exception as e:
            print(f"  ⚠️  {vid}: stats fetch failed ({e}) — will retry next run")
            continue
        if not st:
            print(f"  ⚠️  {vid}: no stats (deleted/private?) — skipping")
            continue
        search = _search_views(token, vid, row["posted_at"]) if analytics_ok else None
        if search is None:
            analytics_ok = False  # don't hammer the API once we know scope is missing
        pct = round(search / st["views"], 3) if (search and st["views"]) else None
        ledger.update(vid, finalized=True, search_views=search, search_pct=pct, **st)
        sv = f", search {search}" if search is not None else ""
        print(f"  ✓ {vid} [{row['theme']}] {st['views']} views{sv} — {row['title']!r}")
        done += 1
    return done


def _score(row: dict) -> int:
    """Reward SEARCH-driven views (the keyword thesis); fall back to total views."""
    sv = row.get("search_views")
    return sv if sv else row.get("views", 0)


def compute_winners() -> dict:
    """Aggregate finalized rows by theme into weights run_pipeline can use."""
    by_theme = defaultdict(list)
    for r in ledger.load():
        if r.get("finalized") and r.get("views") is not None:
            by_theme[r["theme"]].append(r)

    themes = {}
    for theme, rows in by_theme.items():
        n = len(rows)
        avg_views = round(sum(r.get("views", 0) for r in rows) / n, 1)
        avg_score = round(sum(_score(r) for r in rows) / n, 1)
        pcts = [r["search_pct"] for r in rows if r.get("search_pct") is not None]
        themes[theme] = {
            "n": n,
            "avg_views": avg_views,
            "avg_search_views": avg_score,
            "avg_search_pct": round(sum(pcts) / len(pcts), 3) if pcts else None,
            "total_views": sum(r.get("views", 0) for r in rows),
        }

    # Scraped (real footage) vs generated (AI anime) — the head-to-head test.
    by_source = defaultdict(list)
    for r in ledger.load():
        if r.get("finalized") and r.get("views") is not None:
            by_source[r.get("source", "generated")].append(r)
    sources = {s: {"n": len(rows),
                   "avg_views": round(sum(x.get("views", 0) for x in rows) / len(rows), 1),
                   "total_views": sum(x.get("views", 0) for x in rows)}
               for s, rows in by_source.items()}

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "themes": themes,
        "sources": sources,
        # run_pipeline reads this: weight per theme = avg search-driven views.
        "theme_weights": {t: v["avg_search_views"] for t, v in themes.items()},
    }
    WINNERS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


def report(winners: dict) -> None:
    themes = winners.get("themes", {})
    if not themes:
        print("\nNo finalized videos yet — nothing to rank. Post a few, wait ~24h, "
              "and run analyze.py again.")
        return
    ranked = sorted(themes.items(), key=lambda kv: kv[1]["avg_search_views"],
                    reverse=True)
    print("\n" + "=" * 64)
    print("KEYWORD-THEME STANDINGS  (ranked by avg search-driven views)")
    print("=" * 64)
    print(f"{'theme':<18}{'n':>3}{'avg_views':>11}{'search_views':>14}{'search%':>9}")
    for theme, v in ranked:
        pct = f"{v['avg_search_pct']*100:.0f}%" if v["avg_search_pct"] is not None else "—"
        print(f"{theme:<18}{v['n']:>3}{v['avg_views']:>11}"
              f"{v['avg_search_views']:>14}{pct:>9}")
    best, bv = ranked[0]
    print(f"\n🏆 Doubling down on: {best}  "
          f"(avg {bv['avg_search_views']} search views/post)")
    if len(ranked) > 1:
        worst = ranked[-1][0]
        print(f"🪦 Underperforming: {worst} — run_pipeline will show it less often.")

    # The scraped-vs-generated verdict.
    src = winners.get("sources", {})
    if len(src) > 1:
        print("\n" + "-" * 64)
        print("SCRAPED vs GENERATED  (avg views/post)")
        for s, v in sorted(src.items(), key=lambda kv: -kv[1]["avg_views"]):
            print(f"  {s:<12} n={v['n']:<3} avg={v['avg_views']:<8} total={v['total_views']}")
        win = max(src.items(), key=lambda kv: kv[1]["avg_views"])[0]
        print(f"  → {win} is winning. Once the sample is solid, shift the daily mix toward it.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure Shorts + pick winning themes.")
    ap.add_argument("--min-age", type=float, default=24.0,
                    help="Only measure videos at least N hours old (default 24).")
    ap.add_argument("--report", action="store_true",
                    help="Just print standings from existing data; don't re-measure.")
    args = ap.parse_args()

    if not args.report:
        n = measure(args.min_age)
        print(f"\nMeasured {n} video(s).")
    report(compute_winners())


if __name__ == "__main__":
    main()
