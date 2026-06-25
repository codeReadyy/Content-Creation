"""formats/anime_cta.py — original cozy-anime hook + CTA, as a VIDEO Asset.

Reuses the proven pipeline: ghostwriter writes a fresh listicle title+description
(falling back to templates), generate_hook paints the anime hook with that title
burned on, stitch_cta appends the CTA, music_bed lays the lullaby. The on-screen
caption == the title == the description keyword, kept consistent as before.
"""

from __future__ import annotations

from datetime import datetime

import ghostwriter
import music_bed
import run_pipeline
import stitch_cta
from core.models import VIDEO, Asset, BuildContext, Niche
from formats.base import register


class AnimeCTA:
    name = "anime_cta"
    produces = VIDEO

    def build(self, niche: Niche, ctx: BuildContext) -> Asset | None:
        # Fresh LLM copy, else the dedup'd templates (same as today's _make_generated).
        post = (ghostwriter.write_post(ctx.rng, avoid_titles=ctx.avoid_titles)
                or run_pipeline.choose_post(ctx.rng, avoid_titles=ctx.avoid_titles))
        title, description, theme = post["title"], post["description"], post["theme"]

        hook = run_pipeline.get_hook("generated", run_pipeline.WORK_DIR, None,
                                     ctx.slot_index, caption_override=title)
        if not hook:
            print("  ⚠️  anime hook generation failed — skipping.")
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = run_pipeline.QUEUE_DIR / f"short_{stamp}_{hook['slug']}.mp4"
        try:
            stitch_cta.stitch(hook["path"], ctx.cta_path, out)
        except Exception as e:
            print(f"  ⚠️  stitch failed: {e}")
            return None
        music_bed.add_music(out, volume=0.55)  # lullaby is the only audio
        return Asset(kind=VIDEO, paths=[out], theme=theme, source="generated",
                     meta={"title": title, "description": description,
                           "tags": niche.tags, "hook_text": hook.get("title")})


register(AnimeCTA())
