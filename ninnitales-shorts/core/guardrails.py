"""core/guardrails.py — the pre-publish safety net that replaces the human veto.

Going autonomous (no per-post approval), every post passes these checks first. A
failure SKIPS that slot and raises a Telegram alert — it never silently posts junk.

Checks: media files exist; video duration / carousel count within the platform's
limits; title/caption length; a brand-safety lint for over-claim phrases (extendable
per niche via `forbidden_phrases` in the niche YAML). Token health is checked once by
the orchestrator (token_doctor.check), not here.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from core.models import CAROUSEL, VIDEO, Asset, Niche, PostCopy

# Per-platform hard limits (conservative; tighten as needed).
PLATFORM_LIMITS = {
    "youtube":   {"max_video_sec": 180, "title_max": 100},
    "instagram": {"max_video_sec": 90,  "caption_max": 2200, "max_carousel": 10},
    "tiktok":    {"max_video_sec": 600, "caption_max": 2200},
}

# Generic over-claim phrases blocked everywhere; a niche can add its own via
# `forbidden_phrases:` in its YAML (merged in).
DEFAULT_FORBIDDEN = ["guaranteed", "miracle cure", "100% safe", "clinically proven"]


@dataclass
class Verdict:
    ok: bool
    problems: list[str] = field(default_factory=list)

    def reason(self) -> str:
        return "; ".join(self.problems)


def _video_seconds(path: Path) -> float | None:
    """Duration via ffprobe; None if ffprobe is unavailable or fails (skip the check)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=30)
        if out.returncode == 0:
            return float(json.loads(out.stdout)["format"]["duration"])
    except Exception:
        pass
    return None


def check(asset: Asset, copy: PostCopy, platform: str, niche: Niche) -> Verdict:
    problems: list[str] = []
    lim = PLATFORM_LIMITS.get(platform, {})

    # 1. media present
    for p in asset.paths:
        if not Path(p).exists():
            problems.append(f"missing media file: {p}")
    if not asset.paths:
        problems.append("asset has no media")

    # 2. shape per platform
    if asset.kind == VIDEO and asset.paths and Path(asset.path).exists():
        dur = _video_seconds(asset.path)
        if dur is not None and lim.get("max_video_sec") and dur > lim["max_video_sec"]:
            problems.append(f"video {dur:.0f}s > {platform} max {lim['max_video_sec']}s")
    if asset.kind == CAROUSEL:
        if len(asset.paths) < 2:
            problems.append("carousel needs at least 2 slides")
        mx = lim.get("max_carousel")
        if mx and len(asset.paths) > mx:
            problems.append(f"carousel has {len(asset.paths)} slides > {platform} max {mx}")

    # 3. copy length
    if lim.get("title_max") and len(copy.title) > lim["title_max"]:
        problems.append(f"title {len(copy.title)} chars > {lim['title_max']}")
    if lim.get("caption_max") and len(copy.caption) > lim["caption_max"]:
        problems.append(f"caption {len(copy.caption)} chars > {lim['caption_max']}")
    if not copy.title and not copy.caption:
        problems.append("empty copy (no title or caption)")

    # 4. brand-safety lint
    forbidden = list(DEFAULT_FORBIDDEN) + list(niche.extra.get("forbidden_phrases", []))
    blob = f"{copy.title}\n{copy.caption}".lower()
    for phrase in forbidden:
        if phrase.lower() in blob:
            problems.append(f"forbidden phrase: {phrase!r}")

    return Verdict(ok=not problems, problems=problems)
