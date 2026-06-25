"""core/models.py — the shared vocabulary of the content engine.

Two data objects flow through every run:
  • Asset    — what a FORMAT builds (a finished video, or a set of carousel slides)
  • PostCopy — the platform-tailored title/caption a PUBLISHER posts with the Asset

Two config objects describe WHAT to make and WHERE it goes:
  • Niche    — a content profile (brand voice, keyword themes, CTA, fixed titles)
  • Account  — one (platform, account) target + which formats/schedule/niche it runs

And two Protocols define the plugin contracts:
  • Format    — build(niche, rng) -> Asset | None      (formats/*.py)
  • Publisher — publish(asset, copy, account, at) -> {} (publishers/*.py)

Adding a format or publisher = a new file implementing the protocol + a registry
entry; adding an account or niche = a YAML block. Nothing else changes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

# Asset kinds (what a format produces / a publisher accepts).
VIDEO = "video"
CAROUSEL = "carousel"


@dataclass
class Asset:
    """A built piece of content, ready to be captioned and published.

    kind:   VIDEO (one mp4 in paths) or CAROUSEL (N slide images in paths).
    paths:  the media file(s) on disk.
    theme:  the keyword/brand bucket this belongs to (for ledger attribution).
    source: how it was made — "scraped" | "generated" | "carousel" — so analytics
            can compare content types head-to-head.
    meta:   format-specific extras the copywriter may use (e.g. listicle steps,
            the on-screen hook text, the source channel for a scraped clip).
    """
    kind: str
    paths: list[Path]
    theme: str
    source: str
    meta: dict = field(default_factory=dict)

    @property
    def path(self) -> Path:
        """Convenience for single-file (video) assets."""
        return self.paths[0]


@dataclass
class PostCopy:
    """Platform-tailored listing copy for one post."""
    title: str
    caption: str
    tags: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)


@dataclass
class Niche:
    """A content profile — generalizes today's hard-coded NinniTales constants so a
    new niche/product is a YAML file, not code. Loaded from config/niches/<name>.yml."""
    name: str
    product: str
    brand_context: str               # one-paragraph product description for prompts
    ghostwriter_system: str          # SYSTEM prompt for LLM-written (generated) copy
    themes: dict[str, str]           # keyword bucket -> example search query
    tags: list[str]                  # platform tags/keywords (YouTube)
    waitlist_url: str
    cta_dir: str                     # dir of CTA clips, relative to the package root
    # Scraped Shorts: rotating brand titles + ONE fixed brand description.
    scraped_theme: str = "brand"
    scraped_titles: list[str] = field(default_factory=list)
    scraped_description: str = ""
    default_hashtags: list[str] = field(default_factory=list)
    # Selection tunables (explore/exploit + dedup) — sane defaults, overridable.
    min_sample_per_theme: int = 4
    explore_rate: float = 0.20
    dedup_window_days: int = 7
    # Anything else in the YAML is preserved here for forward-compat.
    extra: dict = field(default_factory=dict)


@dataclass
class Account:
    """One distribution target = a (platform, account) pair, from config/accounts.yml.

    creds_env: the env-var SUFFIX for this account's credentials, e.g. "NINNITALES"
               resolves YOUTUBE_*_NINNITALES (see publishers/youtube.py).
    formats:   format names this account is allowed to post (filtered further by
               whether the platform's publisher accepts that format's asset kind).
    gate:      True = require Telegram approval before publishing (for unproven
               accounts); False = fully autonomous.
    """
    id: str
    platform: str
    product: str
    niche: str
    creds_env: str
    formats: list[str]
    schedule_et: list[str]           # ["08:00", "12:30", "19:00"]
    gate: bool = False
    enabled: bool = True
    extra: dict = field(default_factory=dict)


@dataclass
class BuildContext:
    """Everything a format needs for one build, beyond the niche itself.

    rng:          the run's RNG (so selection is reproducible per run).
    avoid_titles: titles used recently (+ already this run) — formats must not repeat.
    cta_path:     the CTA clip to stitch (video formats); None for carousel.
    slot_index:   0-based index of this slot in the run (for alternation/logging).
    cookies:      cookies.txt path for scraping (scraped format); usually None.
    """
    rng: random.Random
    avoid_titles: list[str] = field(default_factory=list)
    cta_path: Path | None = None
    slot_index: int = 0
    cookies: str | None = None


@runtime_checkable
class Format(Protocol):
    """A content format. Stateless; `build` returns a ready-to-publish Asset.

    The Asset's meta SHOULD carry the copy inputs the copywriter needs:
    {"title", "description", "tags", "hashtags", "steps", ...}.
    """
    name: str
    produces: str                    # VIDEO | CAROUSEL

    def build(self, niche: Niche, ctx: BuildContext) -> Asset | None: ...


@runtime_checkable
class Publisher(Protocol):
    """Posts an Asset to one account on a platform."""
    platform: str
    accepts: set[str]                # asset kinds it can post, e.g. {VIDEO}

    def publish(self, asset: Asset, copy: PostCopy, account: Account,
                publish_at: str | None = None) -> dict: ...
