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

import re
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


def _background_kind(scene: str, w: int = W, h: int = H) -> tuple[Image.Image, bool]:
    """(background, is_photo). The text-forward layout needs to know whether it is
    drawing over a real generated scene — which needs a full scrim to stay legible —
    or over our own gradient, which is already dark and looks cleaner untouched."""
    img = _background(scene, w, h)
    return img, img.getpixel((w // 2, h // 2)) != _gradient(w, h).getpixel((w // 2, h // 2))


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


# Copy that belongs in the description FIELD, never burned onto the pin face.
_CTA_MARKERS = ("save this", "try it", "try the", "free at", "sign up", "download",
                "link in", "tap ", "click ", "learn more", "visit ", "swipe")


def _takeaways(description: str, title: str = "", limit: int = 3) -> list[str]:
    """Short value lines pulled from the pin's own description.

    The description is already keyword-first prose written for Pinterest search, so its
    advice can fill the pin face instead of leaving two-thirds of the frame empty. Three
    things have to be filtered out or the face reads as noise: the CTA sentence (it ends
    up truncated to a dangling "...try it free at" once the URL is stripped), the opening
    sentence that just restates the headline, and long comma-chained instructions — which
    carry three separate tips in one sentence and must be split to be readable.
    """
    txt = re.sub(r"https?://\S+", " ", description or "")
    txt = re.sub(r"#\w+", " ", txt)

    chunks: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", txt):
        if len(sent) > 95 and "," in sent:
            chunks += re.split(r",\s*(?:and\s+)?", sent)
        else:
            chunks.append(sent)

    title_words = {w for w in title.lower().split() if len(w) > 3}
    out: list[str] = []
    for chunk in chunks:
        chunk = " ".join(chunk.split()).strip(" .,;:-")
        # A split clause often begins with the conjunction that joined it ("so a
        # familiar voice settles..."), which reads as a fragment on its own line.
        chunk = re.sub(r"^(?:so|and|but|then|which|because|while)\s+", "", chunk,
                       flags=re.I)
        low = chunk.lower()
        if not (18 <= len(chunk) <= 115):
            continue
        if any(m in low for m in _CTA_MARKERS):
            continue
        words = {w for w in low.split() if len(w) > 3}
        # Measured against the TITLE's words, not the chunk's: a line that covers the
        # whole headline is a restatement of the text directly above it, however many
        # extra words it adds ("A calm, repeatable way to handle <the exact title>").
        if title_words and len(words & title_words) / len(title_words) > 0.75:
            continue
        out.append(chunk[:1].upper() + chunk[1:])
        if len(out) == limit:
            break
    return out


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_w: float,
          draw: ImageDraw.ImageDraw) -> list[str]:
    """Greedy wrap measured in PIXELS — textwrap's character count is wrong for a
    proportional face (Poppins 'W' is ~3x 'i')."""
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit_headline(headline: str, draw: ImageDraw.ImageDraw, max_w: float,
                  max_lines: int = 4) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Largest Poppins size that keeps the headline within `max_lines`."""
    for size in range(84, 43, -4):
        font = _font(FONT_BOLD, size)
        lines = _wrap(headline, font, max_w, draw)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(FONT_BOLD, 44)
    return font, _wrap(headline, font, max_w, draw)[:max_lines]


MARGIN = 84
CREAM = (255, 235, 180)


# Theme keys are snake_case identifiers, so the contraction is missing its apostrophe
# and "WONT SLEEP" reads as a typo in the kicker.
_EYEBROW_FIX = {"wont": "won't", "cant": "can't", "dont": "don't",
                "isnt": "isn't", "wasnt": "wasn't", "doesnt": "doesn't"}


def _eyebrow_label(theme: str) -> str:
    words = [_EYEBROW_FIX.get(w, w) for w in theme.replace("_", " ").split()]
    return " ".join(" ".join(words).upper())      # letter-spaced kicker


def _render(headline: str, scene: str, out: Path, eyebrow: str = "",
            tips: list[str] | None = None) -> Path:
    """A TEXT-FORWARD pin: eyebrow, headline, rule, numbered takeaways, brand footer.

    The previous layout hung a headline at the top and a footer at the bottom of a
    background image. With image generation off (no billing) that background is the flat
    gradient, so ~two-thirds of every pin was empty purple. Pinterest is a brand-presence
    surface here, so the frame now carries the pin's own advice.

    Laid out in two passes — measure, then place — because the headline wraps to 1-4
    lines and the tip count varies: a single pass either overflows the footer or leaves
    a dead band at the bottom. The leftover height is spent on the gaps BETWEEN tips
    (capped, so two tips don't drift apart) with the remainder pushing the block down.
    """
    img, is_photo = _background_kind(scene)
    if is_photo:
        # Text now runs the full height, so a top-only scrim no longer covers it.
        img = Image.blend(img, Image.new("RGB", img.size, (12, 8, 28)), 0.55)
    draw = ImageDraw.Draw(img)
    content_w = W - 2 * MARGIN
    top_min, footer_top = 132, H - 210

    # ── measure ──────────────────────────────────────────────────────────────
    eyebrow_h = 68 if eyebrow else 0
    hf, lines = _fit_headline(headline, draw, content_w)
    line_h = int(hf.size * 1.22)
    rule_gap_above, rule_gap_below = 46, 62

    tf = _font(FONT_SEMI, 38)
    tip_h = int(tf.size * 1.34)
    blocks = [(wrapped, len(wrapped) * tip_h)
              for wrapped in (_wrap(t, tf, content_w - 84, draw)
                              for t in (tips or []) if t)]
    base_gap = 34

    def total(bs):
        return (eyebrow_h + len(lines) * line_h + rule_gap_above + rule_gap_below
                + sum(h for _, h in bs) + base_gap * max(0, len(bs) - 1))

    while blocks and total(blocks) > footer_top - top_min:
        blocks.pop()                       # drop the tip that would overflow

    extra = (footer_top - top_min) - total(blocks)
    gap_bonus = min(extra / (len(blocks) + 1), 72) if blocks and extra > 0 else 0
    y = top_min + max(0.0, (extra - gap_bonus * len(blocks)) * 0.45)

    # ── place ────────────────────────────────────────────────────────────────
    if eyebrow:
        ef = _font(FONT_SEMI, 32)
        label = _eyebrow_label(eyebrow)
        draw.text(((W - draw.textlength(label, font=ef)) // 2, y), label,
                  font=ef, fill=CREAM)
        y += eyebrow_h

    for line in lines:
        lw = draw.textlength(line, font=hf)
        draw.text(((W - lw) // 2 + 3, y + 3), line, font=hf, fill=(0, 0, 0))
        draw.text(((W - lw) // 2, y), line, font=hf, fill=(255, 255, 255))
        y += line_h

    y += rule_gap_above
    draw.line([((W - 132) // 2, y), ((W + 132) // 2, y)], fill=CREAM, width=5)
    y += rule_gap_below

    for i, (tip_lines, block_h) in enumerate(blocks, 1):
        cy = y + 20
        draw.ellipse([(MARGIN, cy - 26), (MARGIN + 52, cy + 26)], outline=CREAM, width=3)
        nw = draw.textlength(str(i), font=tf)
        draw.text((MARGIN + 26 - nw / 2, cy - 25), str(i), font=tf, fill=CREAM)
        ty = y
        for tl in tip_lines:
            draw.text((MARGIN + 84, ty), tl, font=tf, fill=(240, 236, 250))
            ty += tip_h
        y = ty + base_gap + gap_bonus

    draw.line([((W - 132) // 2, H - 168), ((W + 132) // 2, H - 168)], fill=CREAM, width=2)
    small = _font(FONT_SEMI, 44)
    brand = "NinniTales · ninnitales.com"
    draw.text(((W - draw.textlength(brand, font=small)) // 2, H - 128), brand,
              font=small, fill=CREAM)
    img.save(out)
    return out


def _template_pin(niche: Niche, rng) -> dict:
    """Deterministic fallback so the format always produces an on-brand pin."""
    theme = rng.choice(list(niche.themes)) if niche.themes else "bedtime_routine"
    query = niche.themes.get(theme, "toddler bedtime routine") if niche.themes else \
        "toddler bedtime routine"
    title = query[:1].upper() + query[1:]
    desc = (f"A calm, repeatable way to handle {query}. "
            "Dim the lights a full hour before bed so melatonin has time to rise. "
            "Keep the room cool, dark and boring — no screens in the last hour. "
            "Play a bedtime story in YOUR own recorded voice, so a familiar voice "
            "settles your little one even on the nights you can't be in the room. "
            f"Save this for tonight and try it free at {niche.waitlist_url}. "
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
        _render(data["title"], scene, out,
                eyebrow=data.get("theme", ""),
                tips=_takeaways(data.get("description", ""), data["title"]))

        hashtags = data.get("hashtags") or niche.default_hashtags
        return Asset(kind=IMAGE, paths=[out], theme=data.get("theme", "bedtime_routine"),
                     source="pin",
                     meta={"title": data["title"], "description": data["description"],
                           "link": link, "board": board,
                           "hashtags": hashtags, "tags": niche.tags})


register(Pin())
