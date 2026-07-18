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
# Distribution-health verdict window: the most recent N finalized IG posts.
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


def ig_distributed(row: dict) -> bool:
    """Did Instagram actually show this post to anyone beyond the follower bubble?

    Rows measured after the distributed-flag rollout carry it explicitly; older rows
    are inferred from reach/views so history doesn't pollute the standings either.
    """
    if row.get("platform") != "instagram":
        return True
    d = row.get("distributed")
    if d is not None:
        return bool(d)
    return ig_row_reach(row) >= IG_DISTRIBUTED_MIN_REACH


def ig_verdict(rows: list[dict]) -> dict:
    """Distribution-health verdict over the last IG_RECENT_WINDOW finalized IG posts.

    This is the meta-level watchdog the loop was missing: theme/CTA optimization is
    meaningless while median reach is single-digit — the account's problem is
    DISTRIBUTION, and the fix is the format mix + time, not a better save-CTA.
    """
    rows = sorted((r for r in rows if r.get("platform") == "instagram"
                   and r.get("finalized") and r.get("views") is not None),
                  key=lambda r: r.get("posted_at") or "")[-IG_RECENT_WINDOW:]
    if len(rows) < 6:
        return {"status": "insufficient_data", "n": len(rows)}
    med = statistics.median(ig_row_reach(r) for r in rows)
    distributed = sum(1 for r in rows if ig_distributed(r))
    return {
        "status": "suppressed" if med < IG_DISTRIBUTED_MIN_REACH else "healthy",
        "median_reach_recent": round(med, 1),
        "distributed_posts": distributed,
        "n": len(rows),
    }
