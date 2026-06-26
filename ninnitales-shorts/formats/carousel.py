"""formats/carousel.py — a multi-slide carousel (images), as a CAROUSEL Asset.

The third content format. An LLM writes a niche-specific carousel (a hook slide, a few
value slides with the NinniTales method woven in, and a CTA slide); a compact PIL
renderer paints each slide on a warm gradient with the Poppins brand font. No AI image
model required (gradient backgrounds), so it runs anywhere; if the LLM call fails it
falls back to a template carousel built from the niche themes.

Routes natively to Instagram (carousel). For YouTube the orchestrator can later turn
the slides into a slideshow Short (slides_to_video); that adapter is a follow-up.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import run_pipeline
from core.models import CAROUSEL, Asset, BuildContext, Niche
from formats.base import register

HERE = Path(__file__).resolve().parent.parent
FONT_BOLD = HERE / "assets" / "fonts" / "Poppins-Bold.ttf"
FONT_SEMI = HERE / "assets" / "fonts" / "Poppins-SemiBold.ttf"
W, H = 1080, 1350                       # Instagram portrait 4:5
BG_TOP, BG_BOTTOM = (38, 28, 74), (96, 64, 140)   # warm dusk gradient


def _llm_carousel(niche: Niche, avoid_titles: list[str]) -> dict | None:
    """Ask the LLM for {headline, slides[], caption, hashtags, theme}. None on failure."""
    try:
        import ghostwriter
        client = ghostwriter._client()
    except Exception:
        return None
    import os
    deployment = (os.environ.get("NINNITALES_CHAT_DEPLOYMENT")
                  or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT"))
    themes = ", ".join(niche.themes)
    avoid = "; ".join(avoid_titles[-12:]) or "(none)"
    system = (f"{niche.brand_context}\n\nYou write Instagram CAROUSEL copy for parents. "
              "Return ONLY JSON: {\"theme\":\"<one theme key>\", \"headline\":\"<bold slide-1 "
              "hook, <8 words>\", \"slides\":[\"slide 2 tip\",\"slide 3 tip (the NinniTales "
              "one, plain words)\",\"slide 4 tip\",\"slide 5 tip\"], \"caption\":\"<IG caption, "
              "2-3 sentences, soft CTA to the app>\", \"hashtags\":[\"#..\",...]}. The slides "
              "are short, real, scannable bedtime advice. NO emojis in the headline.")
    user = (f"Allowed theme keys: {themes}.\nDon't reuse these headlines: {avoid}.\n"
            "Write today's carousel as JSON only.")
    try:
        resp = client.chat.completions.create(
            model=deployment, temperature=1.0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        choice = resp.choices[0]
        if choice.finish_reason == "content_filter" or not choice.message.content:
            return None
        data = json.loads(choice.message.content)
        if data.get("headline") and len(data.get("slides") or []) >= 2:
            return data
    except Exception as e:
        print(f"  ⚠️  carousel LLM failed ({e}) — using template.")
    return None


def _template_carousel(niche: Niche, rng) -> dict:
    """Deterministic fallback so the format always produces something on-brand."""
    theme = rng.choice(list(niche.themes)) if niche.themes else "bedtime"
    return {
        "theme": theme,
        "headline": "5 ways to make bedtime easier tonight",
        "slides": [
            "Start the wind-down an hour early — dim the lights so their body clock catches on.",
            "Play a bedtime story in YOUR recorded voice — a familiar voice settles little "
            "ones faster than a screen (this is the idea behind NinniTales).",
            "Keep the room cool and dark — around 68°F is the sweet spot.",
            "Same three steps every night — bath, book, bed — so bedtime feels predictable.",
        ],
        "caption": "Save this for tonight's bedtime. Record your voice once and let your "
                   f"little one fall asleep to you, any night → {niche.waitlist_url}",
        "hashtags": niche.default_hashtags,
    }


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _gradient() -> Image.Image:
    base = Image.new("RGB", (W, H), BG_TOP)
    top, bot = BG_TOP, BG_BOTTOM
    px = base.load()
    for y in range(H):
        t = y / H
        row = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = row
    return base


def _render_slide(text: str, idx: int, total: int, big: bool, out: Path) -> Path:
    img = _gradient()
    draw = ImageDraw.Draw(img)
    font = _font(FONT_BOLD, 92 if big else 60)
    wrap_at = 16 if big else 26
    lines = textwrap.wrap(text, width=wrap_at) or [text]
    line_h = int((92 if big else 60) * 1.3)
    total_h = line_h * len(lines)
    y = (H - total_h) // 2
    for line in lines:
        w = draw.textlength(line, font=font)
        # soft shadow then text
        draw.text(((W - w) // 2 + 3, y + 3), line, font=font, fill=(0, 0, 0))
        draw.text(((W - w) // 2, y), line, font=font, fill=(255, 255, 255))
        y += line_h
    # page indicator + brand footer
    small = _font(FONT_SEMI, 40)
    draw.text((60, H - 90), f"{idx}/{total}", font=small, fill=(255, 255, 255))
    brand = "NinniTales"
    bw = draw.textlength(brand, font=small)
    draw.text((W - bw - 60, H - 90), brand, font=small, fill=(255, 235, 180))
    img.save(out)
    return out


class Carousel:
    name = "carousel"
    produces = CAROUSEL

    def build(self, niche: Niche, ctx: BuildContext) -> Asset | None:
        data = _llm_carousel(niche, ctx.avoid_titles) or _template_carousel(niche, ctx.rng)
        headline = data["headline"]
        slides_text = [headline] + list(data["slides"])
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = run_pipeline.QUEUE_DIR / f"carousel_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        total = len(slides_text)
        for i, text in enumerate(slides_text, 1):
            p = _render_slide(text, i, total, big=(i == 1), out=out_dir / f"slide_{i}.png")
            paths.append(p)
        caption = data.get("caption") or headline
        return Asset(kind=CAROUSEL, paths=paths, theme=data.get("theme", "bedtime"),
                     source="carousel",
                     meta={"title": headline, "description": caption,
                           "hashtags": data.get("hashtags", niche.default_hashtags),
                           "tags": niche.tags})


register(Carousel())
