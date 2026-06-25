"""formats/scraped_cta.py — real-footage scraped hook + CTA, as a VIDEO Asset.

Scrapes the first ~3s of a fresh Short (via SCRAPE_PROXY in the cloud), stitches the
CTA, lays a quiet lullaby under the clip's own audio. Footage is unreadable, so it
gets a ROTATING brand/social-proof title + ONE fixed brand description (from the
niche), never a content-specific listicle. Returns None if the scrape fails so the
orchestrator can fall back to a generated Short.
"""

from __future__ import annotations

from datetime import datetime

import music_bed
import run_pipeline
import stitch_cta
from core.models import VIDEO, Asset, BuildContext, Niche
from formats.base import register


class ScrapedCTA:
    name = "scraped_cta"
    produces = VIDEO

    def build(self, niche: Niche, ctx: BuildContext) -> Asset | None:
        post = run_pipeline.choose_scraped_post(ctx.rng, avoid_titles=ctx.avoid_titles)
        title, description, theme = post["title"], post["description"], post["theme"]

        hook = run_pipeline.get_hook("scraped", run_pipeline.WORK_DIR, ctx.cookies,
                                     ctx.slot_index, caption_override=title)
        if not hook:
            print("  ⚠️  no scraped hook available (proxy/scrape failed).")
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = run_pipeline.QUEUE_DIR / f"scraped_{stamp}_{hook['slug']}.mp4"
        try:
            stitch_cta.stitch(hook["path"], ctx.cta_path, out)
        except Exception as e:
            print(f"  ⚠️  stitch failed: {e}")
            return None
        music_bed.add_music(out, volume=0.30)  # quiet bed under the clip's own audio
        return Asset(kind=VIDEO, paths=[out], theme=theme, source="scraped",
                     meta={"title": title, "description": description,
                           "tags": niche.tags})


register(ScrapedCTA())
