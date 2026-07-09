"""formats/pin.py — a single tall Pinterest pin (one image), as an IMAGE Asset.

The fourth content format, built for Pinterest — a SEARCH/evergreen surface where a
2:3 graphic + keyword title + keyword description keeps driving traffic for months.

A pin is one 1000x1500 image:
  • copy from ghostwriter.write_pin() — keyword-first title + description + board +
    hashtags, driven by the SAME research signals (themes, winners weights, recent
    performance, dedup) as the YouTube/Instagram paths;
  • the background is a cozy-anime bedtime scene from gpt-image-1 (reusing
    generate_hook.generate_image + _cover_crop), with the headline + NinniTales footer
    overlaid via PIL — so it's on-brand with the anime Shorts;
  • if the image model fails or filters, it falls back to a warm gradient render so the
    format ALWAYS produces something.

Boards are rotated per slot so successive pins spread across the niche's boards
("recycle across boards with fresh images"). The destination link (asset.meta["link"])
is the niche's pinterest_link (default: the waitlist_url) — the whole point of a pin.
"""

from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import ghostwriter
import run_pipeline
from core.models import IMAGE, Asset, BuildContext, Niche
from formats.base import register

HERE = Path(__file__).resolve().parent.parent
FONT_BOLD = HERE / "assets" / "fonts" / "Poppins-Bold.ttf"
FONT_SEMI = HERE / "assets" / "fonts" / "Poppins-SemiBold.ttf"
W, H = 1000, 1500                       # Pinterest 2:3 portrait
BG_TOP, BG_BOTTOM = (38, 28, 74), (96, 64, 140)   # warm dusk gradient (fallback bg)

# Cozy, child-free bedtime SCENES for the AI background. Like generate_hook's HOOK_SYSTEM,
# these EVOKE bedtime via setting (nightlight, empty cozy bed, moonlit window) and never
# ask for a depicted child — image models refuse minors in bedroom scenes.
SCENES = [
    "a softly lit cozy nursery at night, a warm nightlight glowing, an empty little bed "
    "with a plush toy, moonlight through the window",
    "a calm bedroom corner at dusk, a glowing speaker on a shelf, fairy lights, an open "
    "storybook resting on a soft blanket",
    "a peaceful moonlit nursery, stars projected on the ceiling, a rocking chair and a "
    "folded quilt, gentle warm lamplight",
    "a snug reading nook at bedtime, a small lamp casting a golden glow, a stack of "
    "picture books, a sleepy cat curled on a cushion",
]


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def _gradient(w: int = W, h: int = H) -> Image.Image:
    base = Image.new("RGB", (w, h), BG_TOP)
    px = base.load()
    for y in range(h):
        t = y / h
        row = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = row
    return base


def _background(scene: str, w: int = W, h: int = H) -> Image.Image:
    """A cozy-anime bedtime background via gpt-image-1; gradient fallback on any failure.

    Parametrized by size so other formats can reuse it (the Instagram carousel cover
    calls this at 1080x1350)."""
    from io import BytesIO

    import generate_hook
    try:
        raw = generate_hook.generate_image(scene)
        img = Image.open(BytesIO(raw)).convert("RGB")
        return generate_hook._cover_crop(img, w, h)
    except (Exception, SystemExit) as e:
        # generate_image raises SystemExit when image creds are absent; treat any failure
        # (missing creds, safety filter, network) as "fall back to the gradient render".
        print(f"  ⚠️  pin image gen failed ({e}) — using gradient background.")
        return _gradient(w, h)


def _scrim(img: Image.Image, top: bool) -> None:
    """Darken one half so overlaid text stays legible over any photo."""
    w, h = img.size
    band = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(band)
    for y in range(h):
        # opaque toward the chosen edge, fading to transparent at the middle.
        t = (1 - y / (h * 0.6)) if top else ((y - h * 0.4) / (h * 0.6))
        a = int(max(0.0, min(1.0, t)) * 165)
        d.line([(0, y), (w, y)], fill=a)
    overlay = Image.new("RGB", (w, h), (12, 8, 28))
    img.paste(overlay, (0, 0), band)


def _render(headline: str, scene: str, out: Path) -> Path:
    img = _background(scene)
    _scrim(img, top=True)
    draw = ImageDraw.Draw(img)
    font = _font(FONT_BOLD, 78)
    lines = textwrap.wrap(headline, width=20) or [headline]
    line_h = int(78 * 1.28)
    y = 90
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((W - w) // 2 + 3, y + 3), line, font=font, fill=(0, 0, 0))
        draw.text(((W - w) // 2, y), line, font=font, fill=(255, 255, 255))
        y += line_h
    # brand footer
    small = _font(FONT_SEMI, 44)
    brand = "NinniTales · ninnitales.com"
    bw = draw.textlength(brand, font=small)
    draw.text(((W - bw) // 2, H - 110), brand, font=small, fill=(255, 235, 180))
    img.save(out)
    return out


def _template_pin(niche: Niche, rng) -> dict:
    """Deterministic fallback so the format always produces an on-brand pin."""
    theme = rng.choice(list(niche.themes)) if niche.themes else "bedtime_routine"
    query = niche.themes.get(theme, "toddler bedtime routine") if niche.themes else \
        "toddler bedtime routine"
    title = query[:1].upper() + query[1:]
    desc = (f"A calm, repeatable way to handle {query}. Dim the lights an hour early, keep "
            "the room cool and dark, and play a bedtime story in YOUR own recorded voice so "
            "a familiar voice settles your little one — even on the nights you can't be in "
            f"the room. Save this for tonight and try it free at {niche.waitlist_url}. "
            "#toddlersleep #bedtimeroutine #momlife")
    return {"theme": theme, "board": "", "title": title, "description": desc,
            "hashtags": niche.default_hashtags}


class Pin:
    name = "pin"
    produces = IMAGE

    def build(self, niche: Niche, ctx: BuildContext) -> Asset | None:
        boards = list(niche.extra.get("pinterest_boards") or [])
        link = niche.extra.get("pinterest_link") or niche.waitlist_url
        data = ghostwriter.write_pin(ctx.rng, ctx.avoid_titles, niche.themes, boards) \
            or _template_pin(niche, ctx.rng)

        # Rotate boards across RUNS, not just slots: slot_index resets each run, so
        # offsetting by the ledger length (which grows with every post) keeps the
        # rotation advancing — otherwise a 3-pin run would hit boards 0-2 forever.
        base = len(run_pipeline.ledger.load())
        board = (boards[(base + ctx.slot_index) % len(boards)] if boards
                 else (data.get("board") or "Toddler Bedtime"))

        scene = SCENES[ctx.slot_index % len(SCENES)]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = run_pipeline.QUEUE_DIR / f"pin_{stamp}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        _render(data["title"], scene, out)

        hashtags = data.get("hashtags") or niche.default_hashtags
        return Asset(kind=IMAGE, paths=[out], theme=data.get("theme", "bedtime_routine"),
                     source="pin",
                     meta={"title": data["title"], "description": data["description"],
                           "link": link, "board": board,
                           "hashtags": hashtags, "tags": niche.tags})


register(Pin())
