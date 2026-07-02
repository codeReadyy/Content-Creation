"""copywriter.py — turn an Asset's copy inputs into platform-tailored PostCopy.

The format already decided the title/description (scraped brand title, anime
ghostwriter listicle, or carousel headline) and stashed them in asset.meta. This
layer formats them per platform:
  • youtube   — keyword title + value/brand description as the body, niche tags
  • instagram — one caption (title + body + hashtags); no separate title field
The generated-copy LLM itself lives in ghostwriter.py; this is only presentation.
"""

from __future__ import annotations

from core.models import Asset, Niche, PostCopy


def compose(niche: Niche, platform: str, asset: Asset) -> PostCopy:
    m = asset.meta
    title = m.get("title", "")
    body = m.get("description", "")
    tags = m.get("tags") or niche.tags
    hashtags = m.get("hashtags") or niche.default_hashtags

    if platform == "youtube":
        # Title + description verbatim (parity with today); tags drive YT search.
        return PostCopy(title=title, caption=body, tags=tags, hashtags=[])

    if platform == "instagram":
        # IG has no title field — fold title + body into one caption. Hashtags matter.
        caption = body if body else title
        return PostCopy(title=title, caption=caption, tags=[], hashtags=hashtags)

    if platform == "pinterest":
        # Pin has a title AND a description (= body, already keyword-rich with a soft CTA
        # + inline hashtags from the ghostwriter). The publisher reads link/board from
        # asset.meta; copy carries only the visible text.
        return PostCopy(title=title, caption=body or title, tags=[], hashtags=hashtags)

    # Fallback: title + body, niche tags.
    return PostCopy(title=title, caption=body, tags=tags, hashtags=hashtags)
