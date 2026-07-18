"""formats/scraped_cta.py — real-footage scraped hook + CTA, as a VIDEO Asset.

Scrapes the first ~3s of a fresh Short (via SCRAPE_PROXY in the cloud), stitches the
CTA, lays a quiet lullaby under the clip's own audio. Uses the SAME search-keyword
title path as the anime format (ghostwriter → choose_post), so the analytics loop drives
scraped titles too: the footage is generic, but the TITLE carries the winning keyword
(burned on-screen + the YouTube/IG title) for search discovery. The brand/social-proof
claim lives in the description. Returns None if the scrape fails so the orchestrator can
fall back to a generated Short.
"""

from __future__ import annotations

from datetime import datetime

import ghostwriter
import music_bed
import run_pipeline
import stitch_cta
from core.models import VIDEO, Asset, BuildContext, Niche
from formats.base import register


class ScrapedCTA:
    name = "scraped_cta"
    produces = VIDEO

    def build(self, niche: Niche, ctx: BuildContext) -> Asset | None:
        # Keyword title weighted by the analytics winners (loop-connected), same as anime.
        post = (ghostwriter.write_post(ctx.rng, avoid_titles=ctx.avoid_titles)
                or run_pipeline.choose_post(ctx.rng, avoid_titles=ctx.avoid_titles))
        title, theme = post["title"], post["theme"]
        description = f"{post['description']}\n\n{run_pipeline.SOCIAL_PROOF}"

        hook = run_pipeline.get_hook("scraped", run_pipeline.WORK_DIR, ctx.cookies,
                                     ctx.slot_index, caption_override=title)
        if not hook:
            print("  ⚠️  no scraped hook available (proxy/scrape failed).")
            return None
        # Burn the keyword promise onto the clip (an original text layer from second
        # 0), then a VALUE BEAT — one real tip from the post's numbered list — so
        # the clip delivers on the promise on-screen instead of teasing the
        # description. Burn failure falls back to the raw clip — never blocks.
        tips = (post.get("steps")
                or run_pipeline.steps_from_description(post.get("description")))
        try:
            import generate_hook
            burned = run_pipeline.WORK_DIR / f"burn_{hook['slug']}.mp4"
            hook["path"] = generate_hook.burn_caption(hook["path"], title, burned,
                                                      tips=tips)
        except Exception as e:
            print(f"  ⚠️  caption burn failed ({e}) — using raw clip")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = run_pipeline.QUEUE_DIR / f"scraped_{stamp}_{hook['slug']}.mp4"
        try:
            stitch_cta.stitch(hook["path"], ctx.cta_path, out)
        except Exception as e:
            print(f"  ⚠️  stitch failed: {e}")
            return None
        music_bed.add_music(out, volume=0.30)  # quiet bed under the clip's own audio
        # hook_channel/hook_id: WHICH clip carried this post — the audit showed the
        # hook clip (not the title theme) is what separates 1,000-view breakouts from
        # 1-view posts, so analyze.py ranks hook sources with this attribution.
        # cta_clip: WHICH CTA tail this post used (cta1/cta2/...), so the rotating
        # variants become a measurable A/B instead of an unlogged constant.
        return Asset(kind=VIDEO, paths=[out], theme=theme, source="scraped",
                     meta={"title": title, "description": description,
                           "tags": niche.tags, "hook_channel": hook.get("channel"),
                           "hook_id": hook["slug"],
                           "cta_clip": ctx.cta_path.stem if ctx.cta_path else None})


register(ScrapedCTA())
