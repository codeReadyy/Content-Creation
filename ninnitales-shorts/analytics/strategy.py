"""analytics/strategy.py — the strategy layer that closes the learning loop.

Shared by orchestrate.py (to ACT: pick each slot's format from the measured surface
standings) and analyze.py (to REPORT: the same math drives the Telegram digest and
analytics/strategy.json, so what the agent is doing is always visible).

Why this exists: for two weeks winners.json held the answer (instagram/scraped_cta
median ~94 views vs instagram/carousel ~4, reach 1-2 = zero recommendation) while the
orchestrator round-robined the account's single configured format — the analyzer
computed a signal nothing consumed. Rule from that failure: every signal analyze.py
computes must have a consumer here, and every consumer must say what it decided.
"""

from __future__ import annotations

import statistics

# A surface (platform/format) needs this many finalized posts before its median is
# trusted for exploit decisions.
SURFACE_MIN_N = 6
# Below this median views a measured surface counts as NOT DISTRIBUTED (the Jul-2026
# data: suppressed carousels sat at median 4; feed-tested content clears this easily).
SURFACE_DEAD_MEDIAN = 20.0
# A dead surface keeps this share of slots as probes so it can earn its way back the
# moment the platform starts distributing it again (e.g. once the account has
# followers, carousels get follower reach and their median recovers on its own).
PROBE_RATE = 0.20

# An Instagram post whose reach (fallback: views) is under this never left the
# followers-only bubble — it carries ZERO information about content quality, so
# analyze.py excludes it from theme/hook/CTA standings and flags it in the ledger.
IG_DISTRIBUTED_MIN_REACH = 25
# Same idea for YouTube: below this a Short never entered the Shorts feed (the
# Jul-2026 audit: dead posts sat at 0-11 views, every feed-tested one cleared 600+).
YT_FEED_MIN_VIEWS = 20
# Distribution-health verdict window: the most recent N finalized posts per platform.
IG_RECENT_WINDOW = 14


def surface_stats(winners: dict, platform: str, fmt: str) -> dict:
    return (winners.get("surfaces") or {}).get(f"{platform}/{fmt}") or {}


def format_mix(winners: dict, platform: str, formats: list[str]) -> dict[str, float]:
    """{format: slot probability} for one platform's account, from surface medians.

    - unmeasured surface (n < SURFACE_MIN_N): weighted like the current best, so new
      formats get real exploration instead of dying unmeasured;
    - measured-dead surface (median < SURFACE_DEAD_MEDIAN): fixed PROBE_RATE share —
      enough to notice recovery, not enough to waste the feed's patience;
    - healthy surfaces: share proportional to median views.
    With no measured surface at all this is a uniform split (≈ round-robin).
    """
    if not formats:
        return {}
    if len(formats) == 1:
        return {formats[0]: 1.0}
    n = {f: int(surface_stats(winners, platform, f).get("n") or 0) for f in formats}
    med = {f: float(surface_stats(winners, platform, f).get("median_views") or 0.0)
           for f in formats}
    measured = [f for f in formats if n[f] >= SURFACE_MIN_N]
    dead = [f for f in measured if med[f] < SURFACE_DEAD_MEDIAN]
    live = [f for f in formats if f not in dead]
    if not measured or not live:
        return {f: 1.0 / len(formats) for f in formats}
    best = max([med[f] for f in measured] or [1.0])
    weight = {f: (best if n[f] < SURFACE_MIN_N else med[f]) for f in live}
    total = sum(weight.values()) or 1.0
    probe = (PROBE_RATE / len(dead)) if dead else 0.0
    live_mass = 1.0 - probe * len(dead)
    mix = {f: round(live_mass * weight[f] / total, 3) for f in live}
    mix.update({f: round(probe, 3) for f in dead})
    return mix


def describe_mix(mix: dict[str, float]) -> str:
    return " · ".join(f"{f} {p:.0%}" for f, p in
                      sorted(mix.items(), key=lambda kv: -kv[1]))


def ig_row_reach(row: dict) -> int:
    """Best available distribution number for an IG ledger row (reach, else views)."""
    v = row.get("reach")
    if v is None:
        v = row.get("views")
    return int(v or 0)


def distributed(row: dict) -> bool:
    """Did the platform actually show this post to anyone?

    Instagram: the measured `distributed` flag (reach ≥ 25), inferred from
    reach/views on rows that predate the flag. YouTube: the `feed_tested` flag
    (views ≥ 20 = entered the Shorts feed), same inference for older rows. A post
    the platform never distributed says NOTHING about its content — content
    standings must skip it, or the loop learns from noise.
    """
    plat = row.get("platform", "youtube")
    if plat == "instagram":
        d = row.get("distributed")
        if d is not None:
            return bool(d)
        return ig_row_reach(row) >= IG_DISTRIBUTED_MIN_REACH
    if plat == "youtube":
        ft = row.get("feed_tested")
        if ft is not None:
            return bool(ft)
        return int(row.get("views") or 0) >= YT_FEED_MIN_VIEWS
    return True


# Back-compat alias (pre-YouTube generalization).
ig_distributed = distributed


def platform_verdict(rows: list[dict], platform: str) -> dict:
    """Distribution-health verdict over the platform's last IG_RECENT_WINDOW
    finalized posts.

    This is the meta-level watchdog the loop was missing: theme/CTA/title
    optimization is meaningless while the feed shows posts to nobody — the problem
    is DISTRIBUTION, and the fix is mix/cadence/variety, not a better save-CTA.
    """
    reach_of = ig_row_reach if platform == "instagram" \
        else (lambda r: int(r.get("views") or 0))
    floor = IG_DISTRIBUTED_MIN_REACH if platform == "instagram" else YT_FEED_MIN_VIEWS
    rows = sorted((r for r in rows if r.get("platform", "youtube") == platform
                   and r.get("finalized") and r.get("views") is not None),
                  key=lambda r: r.get("posted_at") or "")[-IG_RECENT_WINDOW:]
    if len(rows) < 6:
        return {"status": "insufficient_data", "n": len(rows)}
    med = statistics.median(reach_of(r) for r in rows)
    return {
        "status": "suppressed" if med < floor else "healthy",
        "median_reach_recent": round(med, 1),
        "distributed_posts": sum(1 for r in rows if distributed(r)),
        "n": len(rows),
    }


def ig_verdict(rows: list[dict]) -> dict:
    return platform_verdict(rows, "instagram")


def yt_verdict(rows: list[dict]) -> dict:
    return platform_verdict(rows, "youtube")


# ── Learning while suppressed ───────────────────────────────────────────────────
# The floors above are the right guard for a HEALTHY platform: a post two people saw
# says nothing about its theme. But when the WHOLE platform is suppressed nothing
# clears the floor, so the content standings freeze at whatever was measured before
# the throttle — YouTube's sat on five June breakouts for three weeks while 35 posts
# published into the void, and the picker kept exploiting weights computed from data
# that predates the problem. That's a deadlock, not a guard: suppressed → nothing
# distributed → nothing learned → same content → still suppressed.
#
# So while a platform is suppressed we rank RELATIVELY inside its recent window: a
# row's score becomes its percentile rank there. Percentiles are scale-free, so a
# 4-view post still outranks a 0-view post without anyone claiming 4 views is good.
# Two guards keep this from being astrology — the window needs RELATIVE_MIN_N rows
# AND RELATIVE_MIN_SPREAD between best and worst. A window of all-1s has no ordering
# to learn, so it returns nothing and the picker explores uniformly (the honest
# answer). Everything reverts to the absolute floor the moment feed tests return.
RELATIVE_WINDOW = 40
RELATIVE_MIN_N = 10
RELATIVE_MIN_SPREAD = 4


def _platform_rows(rows: list[dict], platform: str) -> list[dict]:
    """This platform's finalized, measured rows, oldest first."""
    return sorted((r for r in rows if r.get("platform", "youtube") == platform
                   and r.get("finalized") and r.get("views") is not None),
                  key=lambda r: r.get("posted_at") or "")


def relative_scores(rows: list[dict], platform: str) -> dict[str, float]:
    """{video_id: percentile 0-100} within the platform's recent window.

    Empty when the window is too small or too flat to carry ordering information —
    callers must treat that as "learn nothing", never as "everything scores 0".
    """
    window = _platform_rows(rows, platform)[-RELATIVE_WINDOW:]
    if len(window) < RELATIVE_MIN_N:
        return {}
    views = sorted(int(r.get("views") or 0) for r in window)
    if views[-1] - views[0] < RELATIVE_MIN_SPREAD:
        return {}
    n = len(views)
    return {r["video_id"]: round(100.0 * sum(1 for v in views
                                             if v <= int(r.get("views") or 0)) / n, 1)
            for r in window if r.get("video_id")}


def content_rows(rows: list[dict], platform: str) -> tuple[list[dict], dict, str]:
    """(rows allowed to teach content standings, {video_id: score}, basis).

    basis is 'absolute' (healthy — only distributed posts teach, scored on views),
    'relative' (suppressed — the recent window teaches, scored on percentile), or
    'frozen' (suppressed with no usable spread — nothing teaches this round).
    """
    plat_rows = _platform_rows(rows, platform)
    if platform_verdict(rows, platform).get("status") != "suppressed":
        return [r for r in plat_rows if distributed(r)], {}, "absolute"
    scores = relative_scores(rows, platform)
    if not scores:
        return [], {}, "frozen"
    return [r for r in plat_rows if r.get("video_id") in scores], scores, "relative"
