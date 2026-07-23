"""analyze.py — measure each Short ~24h after posting, then pick the winners.

For every ledger row that's >= 24h old and not yet finalized:
  • YouTube Data API  → views / likes / comments       (works with current auth)
  • YouTube Analytics → how many of those views came from SEARCH vs the feed
                        (needs the yt-analytics.readonly scope — re-mint the token
                         with get_youtube_token.py; until then search data is skipped)

It writes the numbers back into the ledger, then aggregates into analytics/winners.json
along several dimensions: by keyword `theme` (run_pipeline biases future titles toward
the themes that earned the most SEARCH-driven views), by source, by platform/format
surface, and by ACCOUNT. Account standings are the head-to-head you actually compare —
each account runs one format, so ranking accounts ranks formats without mixing them in
one feed.

Usage:
    python analyze.py              # measure + print report + write winners.json
    python analyze.py --min-age 24 # only measure videos at least N hours old
    python analyze.py --report     # just print the standings, don't re-measure
"""

import argparse
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

import notify_telegram
import run_pipeline
import upload_youtube
from analytics import ledger
from analytics import strategy

try:
    from core import config as acct_config            # resolve account_id -> creds_env
except Exception:                                      # pragma: no cover
    acct_config = None

DATA_API = "https://www.googleapis.com/youtube/v3/videos"
CHANNELS_API = "https://www.googleapis.com/youtube/v3/channels"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
IG_GRAPH = "https://graph.instagram.com"
WINNERS_PATH = ledger.LEDGER_PATH.parent / "winners.json"
# Daily follower snapshots (the actual growth KPI — views alone hid that the IG
# account sat at 2 followers for 44 posts) + the machine-readable strategy verdict.
FOLLOWERS_PATH = ledger.LEDGER_PATH.parent / "followers.json"
STRATEGY_PATH = ledger.LEDGER_PATH.parent / "strategy.json"


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


# ── Instagram measurement (graph.instagram.com) ─────────────────────────────────
def _ig_creds_env(account_id: str | None) -> str:
    """The env-var suffix holding this IG account's token (from accounts.yml)."""
    if account_id and acct_config is not None:
        try:
            return acct_config.get_account(account_id).creds_env
        except Exception:
            pass
    return "NINNITALES"


def _ig_token(creds_env: str) -> str | None:
    return (os.environ.get(f"INSTAGRAM_ACCESS_TOKEN_{creds_env}")
            or os.environ.get("INSTAGRAM_ACCESS_TOKEN"))


def _ig_insight_value(row: dict):
    if row.get("values"):
        return row["values"][0].get("value")
    tv = row.get("total_value")
    return tv.get("value") if isinstance(tv, dict) else None


def _ig_stats(token: str, media_id: str) -> dict:
    """Likes/comments (media fields) + views (insights). views needs the
    instagram_business_manage_insights scope — returns no 'views' key without it."""
    out: dict = {}
    f = requests.get(f"{IG_GRAPH}/{media_id}",
                     params={"fields": "like_count,comments_count", "access_token": token},
                     timeout=30)
    if f.ok:
        j = f.json()
        out["likes"] = int(j.get("like_count", 0) or 0)
        out["comments"] = int(j.get("comments_count", 0) or 0)
    for metric in ("views", "plays", "reach"):     # reels use 'views'; reach = fallback
        r = requests.get(f"{IG_GRAPH}/{media_id}/insights",
                         params={"metric": metric, "access_token": token}, timeout=30)
        if r.ok:
            data = r.json().get("data", [])
            v = _ig_insight_value(data[0]) if data else None
            if v is not None:
                out["views"] = int(v)
                break
        elif r.status_code == 403 or "permission" in r.text.lower():
            print("  ⚠️  IG insights need the instagram_business_manage_insights scope — "
                  "re-Connect Instagram in the connect-helper to grant it.")
            break
        # 400 = metric not valid for this media → try the next name
    # reach (did IG distribute this at all?) + saves/shares (the distribution signals
    # carousels and the rotating engagement CTAs are judged on). Combined call first;
    # if a media type rejects one metric (400), fall back to per-metric fetches.
    if "views" in out:
        out.update(_ig_insights_bundle(
            token, media_id,
            {"reach": "reach", "saved": "saves", "shares": "shares"}))
    return out


def _ig_insights_bundle(token: str, media_id: str, wanted: dict) -> dict:
    """{api_metric: out_key} → {out_key: int} for every metric that resolves."""
    out: dict = {}

    def take(rows):
        for row in rows:
            name = row.get("name")
            v = _ig_insight_value(row)
            if name in wanted and v is not None:
                out[wanted[name]] = int(v)

    r = requests.get(f"{IG_GRAPH}/{media_id}/insights",
                     params={"metric": ",".join(wanted), "access_token": token},
                     timeout=30)
    if r.ok:
        take(r.json().get("data", []))
        return out
    for metric, key in wanted.items():                 # tolerant per-metric fallback
        r = requests.get(f"{IG_GRAPH}/{media_id}/insights",
                         params={"metric": metric, "access_token": token}, timeout=30)
        if r.ok:
            take(r.json().get("data", []))
    return out


def _measure_instagram(min_age_hours: float) -> int:
    due = ledger.pending(min_age_hours=min_age_hours, platform="instagram")
    done = 0
    for row in due:
        mid = row["video_id"]
        token = _ig_token(_ig_creds_env(row.get("account_id")))
        if not token:
            print(f"  ⚠️  IG {mid}: no token in env — skipping")
            continue
        st = _ig_stats(token, mid)
        if "views" not in st:                       # no insights yet → retry next run
            print(f"  ⏳ IG {mid}: views unavailable (grant insights scope / too new) — will retry")
            continue
        # Did this post ever leave the followers-only bubble? Non-distributed posts
        # carry no information about content quality — compute_winners skips them in
        # the theme/hook/CTA standings so the loop stops learning from noise.
        st["distributed"] = (st.get("reach", st["views"])
                             >= strategy.IG_DISTRIBUTED_MIN_REACH)
        ledger.update(mid, platform="instagram", finalized=True, **st)
        reach = f", reach {st['reach']}" if "reach" in st else ""
        flag = "" if st["distributed"] else "  🚫 not distributed"
        print(f"  ✓ IG {mid} [{row.get('theme')}] {st['views']} views{reach}"
              f" — {row['title']!r}{flag}")
        done += 1
    return done


def _avg_view_pct(token: str, video_id: str, posted_at: str) -> float | None:
    """Average % of the Short watched (loops push it >100%). None if unavailable.

    THE retention signal: the Jul-2026 audit showed every Short that entered the feed
    held >100%, while 'dead' posts had 0 views — they were never tested at all. This
    lets the digest separate 'skipped by the feed' from 'shown but failed'."""
    start = posted_at[:10]
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        r = requests.get(ANALYTICS_API, params={
            "ids": "channel==MINE", "startDate": start, "endDate": end,
            "metrics": "averageViewPercentage", "filters": f"video=={video_id}",
        }, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except requests.RequestException:
        return None
    rows = r.json().get("rows") if r.ok else None
    return round(float(rows[0][0]), 1) if rows else None


# Below this many views a Short effectively never entered the Shorts feed — the
# audit's dead posts sat at 0-11 views while every feed-tested one cleared 600+.
FEED_TEST_MIN_VIEWS = 20


# ── Pinterest measurement (api.pinterest.com/v5) ────────────────────────────────
PIN_ANALYTICS = "https://api.pinterest.com/v5/pins"


def _pinterest_token(creds_env: str) -> str | None:
    """Mint a Pinterest access token from this account's refresh token (or None)."""
    from publishers import pinterest
    creds = {
        "app_id": (os.environ.get(f"PINTEREST_APP_ID_{creds_env}")
                   or os.environ.get("PINTEREST_APP_ID")),
        "app_secret": (os.environ.get(f"PINTEREST_APP_SECRET_{creds_env}")
                       or os.environ.get("PINTEREST_APP_SECRET")),
        "refresh": (os.environ.get(f"PINTEREST_REFRESH_TOKEN_{creds_env}")
                    or os.environ.get("PINTEREST_REFRESH_TOKEN")),
    }
    if not all(creds.values()):
        return None
    try:
        return pinterest.access_token(creds)
    except Exception as e:
        print(f"  ⚠️  Pinterest token refresh failed ({e})")
        return None


def _pin_stats(token: str, pin_id: str, start: str) -> dict:
    """Impressions / saves / pin clicks / outbound clicks via the pin analytics endpoint."""
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    r = requests.get(f"{PIN_ANALYTICS}/{pin_id}/analytics", headers={
        "Authorization": f"Bearer {token}"}, params={
        "start_date": start[:10], "end_date": end,
        "metric_types": "IMPRESSION,SAVE,PIN_CLICK,OUTBOUND_CLICK",
    }, timeout=30)
    if not r.ok:
        return {}
    # v5 returns {"all": {"summary_metrics": {METRIC: value, ...}, "daily_metrics": [...]}}
    summary = (r.json().get("all", {}) or {}).get("summary_metrics", {}) or {}

    def g(k):
        return int(summary.get(k, 0) or 0)
    impressions = g("IMPRESSION")
    outbound = g("OUTBOUND_CLICK")
    out = {"views": impressions, "likes": g("SAVE"),
           "comments": g("PIN_CLICK"), "outbound_clicks": outbound}
    # Pinterest IS a search engine and the product KPI is TRAFFIC, so treat outbound
    # clicks like YouTube's search-driven views — the theme weights then chase the
    # themes that actually send parents to the app, not just impressions.
    out["search_views"] = outbound
    out["search_pct"] = round(outbound / impressions, 3) if impressions else None
    return out


def _is_rss_pinterest(account_id: str | None) -> bool:
    """RSS-published pins never get per-pin API analytics (no Standard access) — they
    are finalized without stats so they don't clog the pending queue forever."""
    if account_id and acct_config is not None:
        try:
            return acct_config.get_account(account_id).extra.get("publish_via") == "rss"
        except Exception:
            pass
    return False


def _measure_pinterest(min_age_hours: float) -> int:
    due = ledger.pending(min_age_hours=min_age_hours, platform="pinterest")
    if not due:
        return 0
    done = 0
    for row in due:
        if _is_rss_pinterest(row.get("account_id")):
            ledger.update(row["video_id"], platform="pinterest", finalized=True,
                          rss=True)
            continue
        creds_env = _ig_creds_env(row.get("account_id"))  # same account_id -> creds_env map
        token = _pinterest_token(creds_env)
        if not token:
            print(f"  ⚠️  Pinterest {row['video_id']}: no token in env — skipping")
            continue
        st = _pin_stats(token, row["video_id"], row["posted_at"])
        if "views" not in st:
            print(f"  ⏳ Pinterest {row['video_id']}: analytics unavailable yet — will retry")
            continue
        ledger.update(row["video_id"], platform="pinterest", finalized=True, **st)
        print(f"  ✓ Pinterest {row['video_id']} [{row.get('theme')}] {st['views']} impr, "
              f"{st['outbound_clicks']} clicks — {row['title']!r}")
        done += 1
    return done


# ── Follower snapshots + the strategy verdict (the loop's missing KPI + watchdog) ─
def _load_followers() -> list[dict]:
    try:
        return json.loads(FOLLOWERS_PATH.read_text())
    except (OSError, ValueError):
        return []


def snapshot_ig_followers() -> list[dict]:
    """Record today's follower count per enabled IG account (idempotent per day).

    Views were measured for weeks while the account sat at 2 followers — the goal
    metric has to be in the loop, or 'growth' optimizes the wrong thing."""
    rows = _load_followers()
    if acct_config is None:
        return rows
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for a in acct_config.load_accounts():
        if a.platform != "instagram":
            continue
        token = _ig_token(a.creds_env)
        igid = (os.environ.get(f"INSTAGRAM_BUSINESS_ACCOUNT_ID_{a.creds_env}")
                or os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID"))
        if not (token and igid):
            print(f"  ⚠️  followers: no IG creds for {a.id} — skipping snapshot")
            continue
        try:
            r = requests.get(f"{IG_GRAPH}/{igid}", params={
                "fields": "followers_count,media_count", "access_token": token},
                timeout=30)
        except requests.RequestException:
            continue
        if not r.ok:
            print(f"  ⚠️  followers: {a.id} fetch failed ({r.status_code})")
            continue
        j = r.json()
        rows = [x for x in rows
                if not (x.get("date") == today and x.get("account_id") == a.id)]
        rows.append({"date": today, "account_id": a.id,
                     "followers": int(j.get("followers_count", 0) or 0),
                     "media_count": int(j.get("media_count", 0) or 0)})
        print(f"  👥 {a.id}: {j.get('followers_count')} followers")
    rows.sort(key=lambda x: (x.get("date", ""), x.get("account_id", "")))
    FOLLOWERS_PATH.write_text(json.dumps(rows, indent=2))
    return rows


def snapshot_yt_subscribers(rows: list[dict] | None = None) -> list[dict]:
    """Record today's subscriber count per enabled YouTube account (idempotent/day).

    Same hole the IG snapshot closed, still open on YouTube: views were tracked for a
    month with no idea whether any of it converted to a subscriber — and subscribers
    are what tell a suppressed channel apart from a recovering one.
    """
    rows = _load_followers() if rows is None else rows
    if acct_config is None:
        return rows
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for a in acct_config.load_accounts():
        if a.platform != "youtube":
            continue
        try:
            token = upload_youtube._access_token(upload_youtube._credentials())
            r = requests.get(CHANNELS_API, params={"part": "statistics", "mine": "true"},
                             headers={"Authorization": f"Bearer {token}"}, timeout=30)
        except Exception as e:
            print(f"  ⚠️  subscribers: {a.id} fetch failed ({e})")
            continue
        items = r.json().get("items", []) if r.ok else []
        if not items:
            print(f"  ⚠️  subscribers: {a.id} returned no channel — skipping snapshot")
            continue
        s = items[0].get("statistics", {})
        rows = [x for x in rows
                if not (x.get("date") == today and x.get("account_id") == a.id)]
        rows.append({"date": today, "account_id": a.id,
                     "followers": int(s.get("subscriberCount", 0) or 0),
                     "media_count": int(s.get("videoCount", 0) or 0)})
        print(f"  👥 {a.id}: {s.get('subscriberCount')} subscribers")
    rows.sort(key=lambda x: (x.get("date", ""), x.get("account_id", "")))
    FOLLOWERS_PATH.write_text(json.dumps(rows, indent=2))
    return rows


def _follower_line(rows: list[dict]) -> str | None:
    """'👥 Followers: 2 (+0 today · +1 in 7d)' per IG account, from followers.json."""
    by_acct: dict[str, list] = defaultdict(list)
    for r in rows:
        if r.get("date") and r.get("followers") is not None:
            by_acct[r.get("account_id", "?")].append(r)
    parts = []
    for acct, hist in by_acct.items():
        hist.sort(key=lambda x: x["date"])
        cur = hist[-1]

        def baseline(days: int):
            cutoff = (datetime.strptime(cur["date"], "%Y-%m-%d")
                      - timedelta(days=days)).strftime("%Y-%m-%d")
            older = [h for h in hist if h["date"] <= cutoff]
            return older[-1]["followers"] if older else None

        seg = f"<b>{cur['followers']}</b>"
        d1, d7 = baseline(1), baseline(7)
        deltas = [f"{cur['followers'] - d:+d} {label}"
                  for d, label in ((d1, "today"), (d7, "in 7d")) if d is not None]
        if deltas:
            seg += f" ({' · '.join(deltas)})"
        parts.append(seg if len(by_acct) == 1 else f"{acct}: {seg}")
    return f"👥 Followers: {' | '.join(parts)}" if parts else None


def write_strategy(winners: dict) -> dict:
    """strategy.json = the watchdog verdict + the learned format mix per multi-format
    account — the machine-readable 'what the agent decided and why' record."""
    rows = ledger.load()
    out: dict = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "instagram": strategy.ig_verdict(rows),
        # orchestrate reads this: suppressed → recovery cadence (1 upload/day).
        "youtube": strategy.yt_verdict(rows),
    }
    if acct_config is not None:
        try:
            mixes = {a.id: strategy.format_mix(winners, a.platform, list(a.formats))
                     for a in acct_config.load_accounts() if len(a.formats) > 1}
            if mixes:
                out["format_mix"] = mixes
        except Exception as e:                          # config trouble never blocks
            print(f"  ⚠️  strategy: mix computation failed ({e})")
    STRATEGY_PATH.write_text(json.dumps(out, indent=2))
    return out


def measure(min_age_hours: float) -> int:
    """Fill in stats for due posts (YouTube + Instagram). Returns how many were finalized."""
    run_pipeline._load_env()
    due = ledger.pending(min_age_hours=min_age_hours)
    done = 0
    if due:
        token = upload_youtube._access_token(upload_youtube._credentials())
        analytics_ok = True
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
            avg_pct = (_avg_view_pct(token, vid, row["posted_at"])
                       if analytics_ok else None)
            tested = st["views"] >= FEED_TEST_MIN_VIEWS
            ledger.update(vid, finalized=True, search_views=search, search_pct=pct,
                          avg_view_pct=avg_pct, feed_tested=tested, **st)
            sv = f", search {search}" if search is not None else ""
            rp = f", ret {avg_pct}%" if avg_pct is not None else ""
            flag = "" if tested else "  🚫 never fed"
            print(f"  ✓ {vid} [{row['theme']}] {st['views']} views{sv}{rp}"
                  f" — {row['title']!r}{flag}")
            done += 1
    else:
        print("No YouTube videos due for measurement.")

    done += _measure_instagram(min_age_hours)
    done += _measure_pinterest(min_age_hours)
    return done


def _score(row: dict) -> int:
    """Reward SEARCH-driven views (the keyword thesis); fall back to total views."""
    sv = row.get("search_views")
    return sv if sv else row.get("views", 0)


# Legacy rows predate the format/platform/account dimensions; back-fill so history
# still counts. Everything before the multi-account engine was the one YouTube channel.
_SOURCE_TO_FORMAT = {"scraped": "scraped_cta", "generated": "anime_cta",
                     "carousel": "carousel"}
LEGACY_ACCOUNT = "ninnitales_yt_main"


def _format_of(row: dict) -> str:
    return row.get("format") or _SOURCE_TO_FORMAT.get(row.get("source", ""), "unknown")


def _platform_of(row: dict) -> str:
    return row.get("platform", "youtube")


def _account_of(row: dict) -> str:
    return row.get("account_id") or LEGACY_ACCOUNT


def compute_winners() -> dict:
    """Aggregate finalized rows by theme into weights run_pipeline can use.

    CONTENT standings (themes, hook types, engagement CTAs, hook sources) only count
    posts the platform actually distributed (strategy.ig_distributed): a carousel 2
    people saw says nothing about its theme. DISTRIBUTION standings (sources,
    surfaces, accounts) keep every row — "this format doesn't get shown" is exactly
    their signal."""
    by_theme = defaultdict(list)
    for r in ledger.load():
        if (r.get("finalized") and r.get("views") is not None
                and strategy.distributed(r)):
            by_theme[r["theme"]].append(r)

    themes = {}
    for theme, rows in by_theme.items():
        n = len(rows)
        views = [r.get("views", 0) for r in rows]
        scores = [_score(r) for r in rows]
        pcts = [r["search_pct"] for r in rows if r.get("search_pct") is not None]
        themes[theme] = {
            "n": n,
            "avg_views": round(sum(views) / n, 1),
            "median_views": round(statistics.median(views), 1),
            "avg_search_views": round(sum(scores) / n, 1),
            # MEDIAN is the trusted signal — one viral fluke can't inflate it (a single
            # 1121-view Short shouldn't crown a theme whose other posts got 5 views).
            "median_search_views": round(statistics.median(scores), 1),
            "avg_search_pct": round(sum(pcts) / len(pcts), 3) if pcts else None,
            "total_views": sum(views),
        }

    # Per-PLATFORM theme stats. _score() is a different UNIT per platform (YouTube =
    # search views, Instagram = raw views, Pinterest = outbound clicks), so a theme's
    # weight is only meaningful within ONE platform — mixing them lets IG's bigger raw
    # numbers inflate a theme for the YouTube picker. Each picker reads its own
    # platform's entry; the global `themes`/`theme_weights` above stay for the report
    # and as a legacy fallback for stale winners.json readers.
    #
    # WHICH rows may teach content standings is decided once, per platform, by
    # strategy.content_rows: a healthy platform contributes only its distributed posts
    # (scored on views); a SUPPRESSED one contributes its recent window scored on
    # PERCENTILE rank instead. Without that second branch the standings freeze the
    # moment a platform is throttled — YouTube's held June's five breakouts for three
    # weeks while 35 posts published to nobody, and the picker kept exploiting them.
    # Percentiles are also gentler weights than raw views: a 0-view theme keeps a
    # nonzero share instead of being permanently excluded from rng.choices.
    all_rows = ledger.load()
    platforms = sorted({_platform_of(r) for r in all_rows
                        if r.get("finalized") and r.get("views") is not None})
    learning_basis: dict[str, str] = {}
    teach: dict[str, float] = {}          # video_id -> the score it teaches with
    for plat in platforms:
        rows_p, rel, basis = strategy.content_rows(all_rows, plat)
        learning_basis[plat] = basis
        if basis == "frozen":
            print(f"  🧊 {plat}: suppressed and its window is too flat to rank — "
                  "content standings held back (the picker explores uniformly)")
        elif basis == "relative":
            print(f"  📐 {plat}: suppressed → content standings ranked RELATIVELY "
                  f"inside the last {len(rows_p)} posts (percentile, not views)")
        for r in rows_p:
            teach[r["video_id"]] = rel[r["video_id"]] if rel else float(_score(r))

    by_plat_theme = defaultdict(lambda: defaultdict(list))
    for r in all_rows:
        if r.get("video_id") in teach:
            by_plat_theme[_platform_of(r)][r["theme"]].append(r)
    themes_by_platform = {}
    for plat in platforms:
        themes_by_platform[plat] = {}
        for theme, rows in by_plat_theme.get(plat, {}).items():
            scores = [teach[r["video_id"]] for r in rows]
            themes_by_platform[plat][theme] = {
                "n": len(rows),
                "median_search_views": round(statistics.median(scores), 1),
                "basis": learning_basis.get(plat, "absolute"),
            }

    # Scraped (real footage) vs generated (AI anime) — the head-to-head test.
    by_source = defaultdict(list)
    for r in ledger.load():
        if r.get("finalized") and r.get("views") is not None:
            by_source[r.get("source", "generated")].append(r)
    sources = {}
    for s, rows in by_source.items():
        views = [x.get("views", 0) for x in rows]
        sources[s] = {"n": len(rows),
                      "avg_views": round(sum(views) / len(views), 1),
                      "median_views": round(statistics.median(views), 1),
                      "total_views": sum(views)}

    # Per-SURFACE standings: "{platform}/{format}" — so the orchestrator can learn that,
    # e.g., anime wins on Instagram while scraped wins on YouTube. Legacy rows (no format/
    # platform) are back-filled from `source` + assumed youtube so history still counts.
    by_surface = defaultdict(list)
    for r in ledger.load():
        if r.get("finalized") and r.get("views") is not None:
            by_surface[f"{_platform_of(r)}/{_format_of(r)}"].append(r)
    surfaces = {}
    for surface, rows in by_surface.items():
        n = len(rows)
        views = [r.get("views", 0) for r in rows]
        scores = [_score(r) for r in rows]
        surfaces[surface] = {
            "n": n,
            "avg_views": round(sum(views) / n, 1),
            "median_views": round(statistics.median(views), 1),
            "avg_search_views": round(sum(scores) / n, 1),
            "median_search_views": round(statistics.median(scores), 1),
            "total_views": sum(views),
        }

    # Per-ACCOUNT standings — the primary comparison now that each account runs ONE
    # format (mixing formats in a single feed confuses the audience). This lets you put
    # the same niche on two channels with different formats and compare the channels
    # head-to-head. Legacy rows (pre multi-account engine) back-fill to the original
    # channel so history still counts. With one format per account, the account's
    # format/platform/niche are consistent across its rows, so the first row labels them.
    by_account = defaultdict(list)
    for r in ledger.load():
        if r.get("finalized") and r.get("views") is not None:
            by_account[_account_of(r)].append(r)
    accounts = {}
    for acct, rows in by_account.items():
        n = len(rows)
        views = [r.get("views", 0) for r in rows]
        scores = [_score(r) for r in rows]
        accounts[acct] = {
            "n": n,
            "platform": _platform_of(rows[0]),
            "format": _format_of(rows[0]),
            "niche": rows[0].get("niche"),
            "avg_views": round(sum(views) / n, 1),
            "median_views": round(statistics.median(views), 1),
            "avg_search_views": round(sum(scores) / n, 1),
            "median_search_views": round(statistics.median(scores), 1),
            "total_views": sum(views),
        }

    # Per-HOOK-SOURCE standings (scraped posts only): the clip is the variable that
    # decides breakouts — the audit's 5 winners (627-1,273 views) were all scraped,
    # with interchangeable titles. Rows predating hook attribution are skipped.
    # NOTE: hook standings deliberately keep NON-distributed rows — a channel whose
    # clips never get feed-tested is exactly what the scraper's channel_order needs
    # to see (its low median demotes it); the `tested` ratio is the channel's hit rate.
    by_hook = defaultdict(list)
    for r in ledger.load():
        if (r.get("finalized") and r.get("views") is not None
                and r.get("hook_channel")):
            by_hook[r["hook_channel"]].append(r)
    hooks = {}
    for ch, rows in by_hook.items():
        views = [r.get("views", 0) for r in rows]
        hooks[ch] = {"n": len(rows),
                     "median_views": round(statistics.median(views), 1),
                     "avg_views": round(sum(views) / len(views), 1),
                     "total_views": sum(views),
                     "tested": sum(1 for r in rows if r.get("feed_tested"))}

    # Per-CAROUSEL-HOOK-TYPE and per-ENGAGEMENT-CTA standings: carousels record which
    # hook style (number_promise/curiosity_gap/...) and engagement mechanic (save/
    # share/caption_bonus/comment_keyword) each post used, so the loop can learn the
    # MECHANIC, not just the topic. NOTE: carousel themes share the global theme_weights
    # namespace with Shorts/pins — harmless, since each consumer validates against its
    # own theme set. Rows predating the attribution are skipped.
    # Eligibility comes from `teach` (above), so these arms keep being ranked while a
    # platform is suppressed instead of emptying out — carousel_hooks/carousel_ctas
    # were both {} for exactly that reason. `median_score` is what pickers should
    # rank on (percentile while suppressed); median_views stays the human-readable one.
    def _dim_standings(key: str) -> dict:
        by = defaultdict(list)
        for r in all_rows:
            if r.get(key) and r.get("video_id") in teach:
                by[r[key]].append(r)
        out = {}
        for k, rows in by.items():
            views = [r.get("views", 0) for r in rows]
            scores = [teach[r["video_id"]] for r in rows]
            out[k] = {"n": len(rows),
                      "median_views": round(statistics.median(views), 1),
                      "median_score": round(statistics.median(scores), 1),
                      "avg_views": round(sum(views) / len(views), 1),
                      "total_views": sum(views),
                      "comments": sum(r.get("comments", 0) for r in rows),
                      "saves": sum(r.get("saves", 0) for r in rows)}
        return out

    carousel_hooks = _dim_standings("hook_type")
    carousel_ctas = _dim_standings("engagement_cta")
    # Which CTA tail (cta1/cta2/...) each video carried — the rotation is only an
    # experiment if the arm is logged and ranked.
    cta_clips = _dim_standings("cta_clip")
    # Which TITLE SHAPE each Short led with. Assigned in code (ghostwriter.TITLE_SHAPES)
    # for the same reason carousel hook types are: left free, the LLM wrote a numbered
    # listicle 82% of the time and the standings had one arm to compare.
    title_shapes = _dim_standings("title_shape")

    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Is YouTube's search attribution actually reporting? _score() falls back to
        # TOTAL views when it isn't, which silently made every `*_search_views` field
        # below a copy of the plain view count — the "search-first" thesis has never
        # once been measured. Readers must check this before believing those keys.
        "search_analytics_live": any(r.get("search_pct") is not None for r in all_rows),
        # How each platform's content standings were computed this round
        # ('absolute' | 'relative' | 'frozen' — see strategy.content_rows).
        "learning_basis": learning_basis,
        "themes": themes,
        "sources": sources,
        "surfaces": surfaces,
        "accounts": accounts,
        "hooks": hooks,
        "carousel_hooks": carousel_hooks,
        "carousel_ctas": carousel_ctas,
        "cta_clips": cta_clips,
        "title_shapes": title_shapes,
        # LEGACY global weights (mixed units across platforms) — kept only so a reader
        # built before the per-platform split still finds something. Pickers should
        # read theme_weights_by_platform instead.
        "theme_weights": {t: v["median_search_views"] for t, v in themes.items()},
        # What pickers actually read: weight per theme = MEDIAN score within ONE
        # platform's KPI (outlier-robust AND unit-consistent).
        "themes_by_platform": themes_by_platform,
        "theme_weights_by_platform": {
            plat: {t: v["median_search_views"] for t, v in tmap.items()}
            for plat, tmap in themes_by_platform.items()},
        # orchestrator format selection can read this: weight per surface (median).
        "surface_weights": {s: v["median_search_views"] for s, v in surfaces.items()},
    }
    WINNERS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


def report(winners: dict) -> None:
    themes = winners.get("themes", {})
    if not themes:
        print("\nNo finalized videos yet — nothing to rank. Post a few, wait ~24h, "
              "and run analyze.py again.")
        return
    ranked = sorted(themes.items(), key=lambda kv: kv[1].get("median_search_views", 0),
                    reverse=True)
    print("\n" + "=" * 64)
    print("KEYWORD-THEME STANDINGS  (ranked by MEDIAN search-driven views)")
    print("=" * 64)
    print(f"{'theme':<18}{'n':>3}{'med_views':>11}{'med_search':>12}{'avg_views':>11}")
    for theme, v in ranked:
        print(f"{theme:<18}{v['n']:>3}{v.get('median_views', 0):>11}"
              f"{v.get('median_search_views', 0):>12}{v['avg_views']:>11}")
    best, bv = ranked[0]
    print(f"\n🏆 Doubling down on: {best}  "
          f"(median {bv.get('median_search_views', 0)} search views/post)")
    if len(ranked) > 1:
        worst = ranked[-1][0]
        print(f"🪦 Underperforming: {worst} — run_pipeline will show it less often.")

    # Per-account standings — the head-to-head now that each account runs one format.
    accts = winners.get("accounts", {})
    if accts:
        print("\n" + "-" * 64)
        print("ACCOUNT STANDINGS  (one format per account; median views/post)")
        print(f"{'account':<22}{'fmt':<13}{'n':>3}{'median':>9}{'avg':>9}{'total':>9}")
        for acct, v in sorted(accts.items(), key=lambda kv: -kv[1].get("median_views", 0)):
            print(f"{acct:<22}{v['format']:<13}{v['n']:>3}"
                  f"{v.get('median_views', 0):>9}{v['avg_views']:>9}{v['total_views']:>9}")
        if len(accts) > 1:
            win = max(accts.items(), key=lambda kv: kv[1].get("median_views", 0))
            print(f"  → {win[0]} ({win[1]['format']}) leads by median. Compare once each "
                  "account has a solid sample.")

    # Hook-source standings — which scraped channel's clips actually carry posts.
    hks = winners.get("hooks", {})
    if hks:
        print("\n" + "-" * 64)
        print("HOOK-SOURCE STANDINGS  (scraped clips; median views/post)")
        for ch, v in sorted(hks.items(), key=lambda kv: -kv[1]["median_views"]):
            print(f"  {ch:<22} n={v['n']:<3} median={v['median_views']:<8} "
                  f"tested={v['tested']}/{v['n']}  total={v['total_views']}")

    # Carousel hook-style + engagement-CTA standings — which MECHANICS win on IG.
    for key, label in (("carousel_hooks", "CAROUSEL HOOK-TYPE STANDINGS"),
                       ("carousel_ctas", "CAROUSEL ENGAGEMENT-CTA STANDINGS")):
        std = winners.get(key, {})
        if std:
            print("\n" + "-" * 64)
            print(f"{label}  (median views/post)")
            for k, v in sorted(std.items(), key=lambda kv: -kv[1]["median_views"]):
                print(f"  {k:<18} n={v['n']:<3} median={v['median_views']:<8} "
                      f"saves={v['saves']:<5} comments={v['comments']}")

    # The scraped-vs-generated verdict (by MEDIAN — one viral fluke shouldn't decide it).
    src = winners.get("sources", {})
    if len(src) > 1:
        print("\n" + "-" * 64)
        print("SCRAPED vs GENERATED  (median views/post)")
        for s, v in sorted(src.items(), key=lambda kv: -kv[1].get("median_views", 0)):
            print(f"  {s:<12} n={v['n']:<3} median={v.get('median_views', 0):<7} "
                  f"avg={v['avg_views']:<8} total={v['total_views']}")
        win = max(src.items(), key=lambda kv: kv[1].get("median_views", 0))[0]
        print(f"  → {win} leads by median. Once the sample is solid, shift the mix toward it.")


def _engagement_rate(rows: list[dict]) -> tuple[int, float]:
    """(total views, engagement % = (likes+comments)/views) across rows."""
    views = sum(r.get("views", 0) for r in rows)
    inter = sum(r.get("likes", 0) + r.get("comments", 0) for r in rows)
    return views, (round(100 * inter / views, 1) if views else 0.0)


def _agent_actions(themes: dict, ranked: list) -> list[str]:
    """Plain-language summary of the levers the selection logic is pulling — so the
    Telegram digest explains WHAT the agent is changing to push the numbers up."""
    floor = run_pipeline.MIN_SAMPLE_PER_THEME
    acts: list[str] = []
    ready = [(t, v) for t, v in ranked if v["n"] >= floor]
    exploring = [t for t, v in themes.items() if v["n"] < floor]
    if ready:
        thr = statistics.median([v["median_search_views"] for _, v in ready])
        boost = [t for t, v in ready if v["median_search_views"] >= thr]
        demote = [t for t, v in ready if v["median_search_views"] < thr]
        if boost:
            acts.append(f"Doubling down on: <b>{', '.join(boost[:3])}</b>")
        if demote:
            acts.append(f"Showing less: {', '.join(demote[:3])}")
    if exploring:
        acts.append(f"Still exploring {len(exploring)} theme(s) — need ≥{floor} posts each "
                    "before trusting their numbers")
    acts.append(f"~{int(run_pipeline.EXPLORE_RATE * 100)}% of picks kept for fresh angles; "
                f"no title reused within {run_pipeline.DEDUP_WINDOW_DAYS} days")
    return acts


def _platform_block(label: str, rows: list[dict]) -> str:
    """One platform's performance: posts, total views, engagement %, MEDIAN (the typical
    post — robust to a viral outlier), and the recent-avg trend."""
    rows = sorted(rows, key=lambda r: r.get("posted_at", ""))
    tv, eng = _engagement_rate(rows)
    med = statistics.median([r.get("views", 0) for r in rows])
    last3, prev3 = rows[-3:], rows[-6:-3]
    a_last = sum(r.get("views", 0) for r in last3) / len(last3) if last3 else 0
    trend = ""
    if prev3:
        a_prev = sum(r.get("views", 0) for r in prev3) / len(prev3)
        if a_prev:
            d = round(100 * (a_last - a_prev) / a_prev)
            trend = f"  ({'↑' if d >= 0 else '↓'}{abs(d)}% vs prior)"
    return (f"\n<b>{label}</b> — {len(rows)} posts · {tv:,} views · {eng}% eng"
            f"\n   <b>median {med:.0f}/post</b> · recent avg {a_last:.0f}{trend}")


def telegram_digest(winners: dict) -> None:
    """Send a performance + decisions digest to Telegram (no-op if unconfigured).

    Answers: how are posts doing PER PLATFORM (views + engagement + trend), which content
    is winning, and what the agent is changing to improve the numbers."""
    if not notify_telegram.configured():
        return
    today = datetime.now(timezone.utc).strftime("%b %d")
    rows = [r for r in ledger.load()
            if r.get("finalized") and r.get("views") is not None]
    if not rows:
        notify_telegram.send_message(
            f"📊 <b>NinniTales — Analysis ({today})</b>\nNo measured posts yet — "
            "post a few and check back ~24h later.")
        return

    by_plat: dict[str, list] = defaultdict(list)
    for r in rows:
        by_plat[r.get("platform", "youtube")].append(r)

    themes = winners.get("themes", {})
    ranked = sorted(themes.items(), key=lambda kv: kv[1].get("median_search_views", 0),
                    reverse=True)
    lines = [f"📊 <b>NinniTales — Daily Analysis ({today})</b>",
             f"{len(rows)} posts measured across {len(by_plat)} platform(s)"]
    for plat, label in (("youtube", "📺 YouTube"), ("instagram", "📸 Instagram"),
                        ("pinterest", "📌 Pinterest")):
        if by_plat.get(plat):
            lines.append(_platform_block(label, by_plat[plat]))

    # Instagram growth reality-check: the follower KPI, the distribution verdict, and
    # the format mix the orchestrator will act on — the digest must say when the
    # numbers are noise (suppressed) instead of ranking noise as "winners".
    fl = _follower_line(_load_followers())
    if fl:
        lines.append(f"\n{fl}")
    v = strategy.ig_verdict(rows)
    if v.get("status") == "suppressed":
        lines.append(
            f"🧭 <b>IG distribution: SUPPRESSED</b> — median reach "
            f"{v['median_reach_recent']}/post over the last {v['n']} posts "
            f"(followers-only; the feed isn't recommending these). Theme/CTA "
            f"standings exclude these posts.")
    elif v.get("status") == "healthy":
        lines.append(f"🧭 IG distribution: healthy — median reach "
                     f"{v['median_reach_recent']}/post (last {v['n']} posts).")
    if acct_config is not None:
        try:
            for a in acct_config.load_accounts():
                if a.platform == "instagram" and len(a.formats) > 1:
                    mix = strategy.format_mix(winners, "instagram", list(a.formats))
                    lines.append(f"🎛 Learned slot mix ({a.id}): "
                                 f"{strategy.describe_mix(mix)}")
        except Exception:
            pass

    # YouTube gets the same watchdog: when the feed stops testing uploads, the agent
    # thins cadence (orchestrate reads strategy.json) — say so instead of ranking noise.
    yv = strategy.yt_verdict(rows)
    if yv.get("status") == "suppressed":
        lines.append(
            f"🧯 <b>YT distribution: SUPPRESSED</b> — median "
            f"{yv['median_reach_recent']:.0f} views over the last {yv['n']} Shorts "
            f"({yv['distributed_posts']} feed-tested). Recovery cadence: 1 upload/day "
            "until feed tests return.")
    elif yv.get("status") == "healthy":
        lines.append(f"🧯 YT distribution: healthy — median "
                     f"{yv['median_reach_recent']:.0f} views (last {yv['n']}).")

    # Feed-test diagnosis: "skipped by the feed" and "shown but failed" need opposite
    # fixes (dedupe/frequency vs content) — say which is happening.
    yt = by_plat.get("youtube", [])
    if yt:
        skipped = sum(1 for r in yt if r.get("views", 0) < FEED_TEST_MIN_VIEWS)
        if skipped:
            lines.append(f"\n🚫 <b>{skipped}/{len(yt)}</b> YouTube posts never entered "
                         "the Shorts feed (<20 views) — repetition throttling, not "
                         "audience rejection. Tested posts' retention:")
            pcts = [r["avg_view_pct"] for r in yt
                    if r.get("avg_view_pct") and r.get("views", 0) >= FEED_TEST_MIN_VIEWS]
            if pcts:
                lines.append(f"   👀 avg {sum(pcts)/len(pcts):.0f}% watched "
                             f"(>100% = loops) across {len(pcts)} tested posts")
    hks = winners.get("hooks", {})
    ready_hooks = {c: v for c, v in hks.items() if v["n"] >= 2}
    if ready_hooks:
        top = max(ready_hooks.items(), key=lambda kv: kv[1]["median_views"])
        lines.append(f"🎣 Best hook source: <b>{top[0]}</b> "
                     f"({top[1]['median_views']:.0f} median, n={top[1]['n']})")
    for key, label in (("carousel_hooks", "Best carousel hook"),
                       ("carousel_ctas", "Best carousel CTA"),
                       ("cta_clips", "Best CTA clip")):
        ready = {k: v for k, v in (winners.get(key) or {}).items() if v["n"] >= 2}
        if ready:
            top = max(ready.items(), key=lambda kv: kv[1]["median_views"])
            lines.append(f"🃏 {label}: <b>{top[0]}</b> "
                         f"({top[1]['median_views']:.0f} median, n={top[1]['n']})")
    if ranked:
        b = ranked[0]
        lines.append(f"\n🏆 Best theme: <b>{b[0]}</b> — {b[1].get('median_views', 0):.0f} "
                     f"median views (n={b[1]['n']})")
        if len(ranked) > 1:
            w = ranked[-1]
            lines.append(f"🪦 Weakest: {w[0]} — {w[1].get('median_views', 0):.0f} median "
                         f"(n={w[1]['n']})")
    src = winners.get("sources", {})
    if len(src) > 1:
        sv = sorted(src.items(), key=lambda kv: -kv[1].get("median_views", 0))
        lines.append(f"🎬 {sv[0][0]} ({sv[0][1].get('median_views', 0):.0f}) vs "
                     f"{sv[1][0]} ({sv[1][1].get('median_views', 0):.0f}) median views")
    accts = winners.get("accounts", {})
    if len(accts) > 1:
        a0 = sorted(accts.items(), key=lambda kv: -kv[1].get("median_views", 0))[0]
        lines.append(f"🏅 Top account: {a0[0]} ({a0[1].get('median_views', 0):.0f} median)")

    for a in (["\n🤖 <b>What the agent is doing</b>"] + _agent_actions(themes, ranked)):
        lines.append(a if a.startswith(("\n", "🤖")) else f"• {a}")
    notify_telegram.send_message("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure Shorts + pick winning themes.")
    ap.add_argument("--min-age", type=float, default=24.0,
                    help="Only measure videos at least N hours old (default 24).")
    ap.add_argument("--report", action="store_true",
                    help="Just print standings from existing data; don't re-measure.")
    ap.add_argument("--no-telegram", action="store_true",
                    help="Skip the Telegram digest (still prints + writes winners.json).")
    args = ap.parse_args()

    if not args.report:
        n = measure(args.min_age)
        print(f"\nMeasured {n} video(s).")
        # Both KPIs land in followers.json; chain them so one write wins the file.
        snapshot_yt_subscribers(snapshot_ig_followers())
    winners = compute_winners()
    write_strategy(winners)
    report(winners)
    if not args.no_telegram:
        telegram_digest(winners)


if __name__ == "__main__":
    main()
