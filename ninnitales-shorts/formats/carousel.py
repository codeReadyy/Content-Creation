"""formats/carousel.py — a multi-slide carousel (images), as a CAROUSEL Asset.

The third content format, and the primary INSTAGRAM format: value-first swipeable
slides (parenting is the save-heaviest niche on IG, and saves/shares are the strongest
distribution signals).

Two visual systems, selected by the niche's `carousel_style`:

  • "flashcard" (current NinniTales IG style) — flat typographic cards modeled on the
    top parenting accounts (Big Little Feelings, Good Inside, Solid Starts): a dark
    night-blue cover + CTA slide bookending cream inner cards, big left-aligned type,
    one point per slide, a numbered gold badge for listicles, tiny handle on cover +
    last slide ONLY (no watermark on value slides). The cover background can be a REAL
    photo from assets/library/ (user-curated, theme-tagged, kids never identifiable),
    falling back to the flat dark card. No AI image calls — a build takes seconds.
    Content is chosen in code (theme via winners.json explore/exploit, brand cadence
    ~2-in-3, a rotating engagement CTA) and the LLM writes value-first, age-aware
    (kids 1-7) slides with zero brand mention outside the final slide.

  • legacy (any other/absent value) — every slide gets an AI background (photoreal
    consistent parent via characters.scene for `carousel_cover_style: realistic`,
    else the cozy-anime pin background) with centered veiled text. Kept intact for
    other accounts and future flat-vs-photo A/Bs.

Everything degrades gracefully: LLM down → template carousel; empty/missing photo
library → flat cover; comment-keyword CTA auto-disables when engage.py has recorded
that the token lacks the comments scope.
"""

from __future__ import annotations

import json
import re
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import run_pipeline
from core.models import CAROUSEL, Asset, BuildContext, Niche
from formats.base import register

HERE = Path(__file__).resolve().parent.parent
FONT_BOLD = HERE / "assets" / "fonts" / "Poppins-Bold.ttf"
FONT_SEMI = HERE / "assets" / "fonts" / "Poppins-SemiBold.ttf"
W, H = 1080, 1350                       # Instagram portrait 4:5
BG_TOP, BG_BOTTOM = (38, 28, 74), (96, 64, 140)   # warm dusk gradient (legacy)

# ── Flashcard style ──────────────────────────────────────────────────────────────
MARGIN = 90
CONTENT_W = W - 2 * MARGIN

# Warm-cream day cards bookended by night-blue cover/CTA cards — a recognizable
# brand system without a watermark on every slide. Overridable per niche via
# `carousel_palette:` (hex strings) in the niche YAML.
PALETTE = {
    "bg":     (251, 243, 228),   # cream card top          #FBF3E4
    "bg2":    (243, 232, 210),   # cream card bottom       #F3E8D2
    "ink":    (31, 42, 68),      # headline/body text      #1F2A44
    "muted":  (98, 108, 134),    # supporting text/counter #626C86
    "accent": (214, 158, 46),    # gold badges/rules/cues  #D69E2E
    "dark":   (34, 48, 79),      # night-blue card top     #22304F
    "dark2":  (26, 37, 62),      # night-blue card bottom  #1A253E
    "cream":  (249, 240, 222),   # text on dark cards      #F9F0DE
}

LIBRARY_DIR = HERE / "assets" / "library"
LIBRARY_MANIFEST = LIBRARY_DIR / "manifest.json"
LIBRARY_USAGE = LIBRARY_DIR / ".usage.json"
LIBRARY_REUSE_DAYS = 30

# engage.py records whether the IG token can actually reply to comments; the
# comment-keyword CTA is only offered while that's believed true, so a post never
# promises a reply the responder can't deliver.
ENGAGE_STATE = HERE / "analytics" / "engage_state.json"

HOOK_TYPES = ("number_promise", "curiosity_gap", "mistake", "relatable_pain")
# The hook type is ASSIGNED in code (like theme + CTA), never left to the LLM: left
# free, GPT picked number_promise 14/14 times ("5 ways to ..."), which made every
# headline near-identical AND left the carousel_hooks standings a one-armed bandit
# with nothing to compare.
HOOK_SPECS = {
    "number_promise": ('a numbered promise of a concrete payoff — like "5 games that '
                       'buy you 20 quiet minutes". The headline STARTS with the number.'),
    "curiosity_gap": ('opens a gap only the swipe closes — like "What calm parents do '
                      'differently at 7pm" or "The 20-second trick before every nap". '
                      'NO number at the start.'),
    "mistake": ('names a mistake the reader is probably making, direct "you" voice — '
                'like "You\'re handling tantrums backwards" or "Stop saying calm '
                'down". NO number at the start.'),
    "relatable_pain": ('drops the reader into the exact hard moment, present tense — '
                       'like "It\'s 9pm and they\'re still awake". NO number at the '
                       'start.'),
}
HOOK_MIN_SAMPLE = 3           # measured posts per hook type before exploiting
HOOK_EXPLORE_RATE = 0.25      # fraction of picks kept uniform even after coverage
CAROUSEL_FORMATS = ("listicle", "do_instead", "myth_truth", "scripts")
# (cta type, weight): save is the default parenting-niche winner; the others rotate
# in so analyze.py can rank the mechanics (carousel_ctas standings).
ENGAGEMENT_CTAS = (("save", 40), ("share", 20), ("caption_bonus", 20),
                   ("comment_keyword", 20))

_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emoji blocks
    "\U00002600-\U000027BF"   # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"   # flags
    "\U00002190-\U000021FF"   # arrows (Poppins has no glyphs; we draw our own)
    "\U00002B00-\U00002BFF"
    "️‍⃣"
    "]+")


def _strip_emoji(text: str) -> str:
    """Poppins renders emoji as tofu boxes — every string that hits a slide goes
    through here (captions keep their emojis; they never touch the renderer)."""
    return _EMOJI_RE.sub("", text or "").strip()


def _hex_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def _palette(niche: Niche) -> dict:
    pal = dict(PALETTE)
    for k, v in (niche.extra.get("carousel_palette") or {}).items():
        if k in pal and isinstance(v, str):
            try:
                pal[k] = _hex_rgb(v)
            except ValueError:
                pass
    return pal


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _handle(niche: Niche) -> str:
    return niche.extra.get("ig_handle") or f"@{niche.product}"


def _card(top: tuple, bottom: tuple) -> Image.Image:
    """A subtle vertical gradient card — flat enough to read as a solid brand color."""
    img = Image.new("RGB", (W, H), top)
    px = img.load()
    for y in range(H):
        row = _mix(top, bottom, y / H)
        for x in range(W):
            px[x, y] = row
    return img


def _wrap_px(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    """Pixel-accurate greedy wrap (textwrap counts chars, which mis-wraps at 100px)."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and draw.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [text]


def _fit(draw: ImageDraw.ImageDraw, text: str, font_path: Path, start: int,
         max_w: int, max_lines: int, min_size: int):
    """Auto-shrink until the text fits max_lines. Returns (font, lines, size)."""
    size = start
    while True:
        font = _font(font_path, size)
        lines = _wrap_px(draw, text, font, max_w)
        if len(lines) <= max_lines or size <= min_size:
            return font, lines, size
        size -= 8


def _tracked(draw: ImageDraw.ImageDraw, xy: tuple, text: str, font, fill,
             tracking: int = 6) -> None:
    """Letter-spaced text (for the kicker eyebrow line)."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def _arrow(draw: ImageDraw.ImageDraw, x_right: int, y_mid: int, color,
           length: int = 64, thickness: int = 8) -> None:
    """A drawn forward arrow (Poppins has no → glyph)."""
    draw.line([(x_right - length, y_mid), (x_right - 16, y_mid)],
              fill=color, width=thickness)
    draw.polygon([(x_right, y_mid), (x_right - 26, y_mid - 15),
                  (x_right - 26, y_mid + 15)], fill=color)


# ── Photo-library covers (user-curated real photos; kids never identifiable) ────
def _cover_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    img = img.resize((int(sw * scale) + 1, int(sh * scale) + 1))
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def _library_cover(theme_key: str, phrase: str, age_band: str, rng) -> Image.Image | None:
    """A real photo from assets/library/ matching the theme, cropped + scrimmed for
    the cover headline. None (→ flat dark card) when the library is empty/unmatched.

    manifest.json: [{"file": "IMG_001.jpg", "tags": ["sleep","mess"], "age": "1-3"}].
    Photos aren't reused within LIBRARY_REUSE_DAYS (tracked in .usage.json)."""
    entries = _load_json(LIBRARY_MANIFEST, [])
    if not isinstance(entries, list) or not entries:
        return None
    want = set(theme_key.replace("_", " ").split()) | set(phrase.lower().split())

    usage = _load_json(LIBRARY_USAGE, {})
    cutoff = datetime.now(timezone.utc) - timedelta(days=LIBRARY_REUSE_DAYS)

    def fresh(name: str) -> bool:
        try:
            return datetime.fromisoformat(usage.get(name, "1970-01-01")) \
                .replace(tzinfo=timezone.utc) < cutoff
        except ValueError:
            return True

    scored = []
    for e in entries:
        name = e.get("file")
        if not name or not (LIBRARY_DIR / name).exists():
            continue
        tags = {str(t).lower() for t in (e.get("tags") or [])}
        score = len(tags & want)
        if e.get("age") and age_band and e["age"] in (age_band, "1-7"):
            score += 1
        scored.append((score, fresh(name), name))
    if not scored:
        return None
    # Prefer topical + fresh; degrade to topical, then to any fresh photo. A zero-score
    # stale-only library yields None → flat cover (never block a post on a photo).
    for pool in ([n for s, f, n in scored if s > 0 and f],
                 [n for s, f, n in scored if s > 0],
                 [n for s, f, n in scored if f]):
        if pool:
            pick = rng.choice(pool)
            break
    else:
        return None
    try:
        img = _cover_crop(Image.open(LIBRARY_DIR / pick).convert("RGB"), W, H)
    except OSError as e:
        print(f"  ⚠️  library photo {pick} unreadable ({e}) — flat cover.")
        return None
    from formats import pin as pin_fmt
    pin_fmt._scrim(img, top=True)          # headline sits in the upper 2/3
    _veil(img, alpha=60)                   # gentle overall veil for contrast safety
    usage[pick] = datetime.now(timezone.utc).date().isoformat()
    try:
        LIBRARY_USAGE.write_text(json.dumps(usage, indent=2))
    except OSError:
        pass
    print(f"  📷 library cover: {pick}")
    return img


# ── Flashcard renderers ──────────────────────────────────────────────────────────
def _render_cover_flash(headline: str, kicker: str, niche: Niche, pal: dict,
                        photo: Image.Image | None, out: Path) -> Path:
    img = photo if photo is not None else _card(pal["dark"], pal["dark2"])
    draw = ImageDraw.Draw(img)
    # tiny muted handle — cover + CTA slide only, never on value slides
    draw.text((MARGIN, 84), _handle(niche), font=_font(FONT_SEMI, 34),
              fill=_mix(pal["cream"], pal["dark"], 0.30))
    if kicker:
        _tracked(draw, (MARGIN, 214), kicker.upper(), _font(FONT_SEMI, 34),
                 pal["accent"])
    font, lines, size = _fit(draw, headline, FONT_BOLD, 100, CONTENT_W, 5, 72)
    y = 300
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=pal["cream"])
        y += int(size * 1.16)
    draw.rectangle([MARGIN, y + 48, MARGIN + 140, y + 58], fill=pal["accent"])
    # swipe cue bottom-right
    cue_font = _font(FONT_SEMI, 40)
    cue = "swipe"
    cue_w = draw.textlength(cue, font=cue_font)
    arrow_w = 78
    draw.text((W - MARGIN - arrow_w - 18 - cue_w, H - 158), cue,
              font=cue_font, fill=pal["accent"])
    _arrow(draw, W - MARGIN, H - 132, pal["accent"])
    img.save(out, quality=90)
    return out


def _render_point_flash(num: int, title: str, body: str, page: int, total: int,
                        pal: dict, numbered: bool, out: Path) -> Path:
    img = _card(pal["bg"], pal["bg2"])
    draw = ImageDraw.Draw(img)
    if numbered:
        cx, cy, r = 144, 154, 54
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=pal["accent"])
        nfont = _font(FONT_BOLD, 54)
        ns = str(num)
        nw = draw.textlength(ns, font=nfont)
        asc, desc = nfont.getmetrics()
        draw.text((cx - nw / 2, cy - (asc + desc) / 2), ns, font=nfont,
                  fill=pal["bg"])
    else:
        draw.rectangle([MARGIN, 120, MARGIN + 140, 130], fill=pal["accent"])
    font, lines, size = _fit(draw, title, FONT_BOLD, 76, CONTENT_W, 3, 58)
    y = 270
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=pal["ink"])
        y += int(size * 1.18)
    if body:
        bfont = _font(FONT_SEMI, 44)
        y += 44
        for line in _wrap_px(draw, body, bfont, CONTENT_W)[:4]:
            draw.text((MARGIN, y), line, font=bfont, fill=pal["muted"])
            y += int(44 * 1.35)
    # page counter bottom-left; forward arrow bottom-right — the swipe engine.
    draw.text((MARGIN, H - 128), f"{page}/{total}", font=_font(FONT_SEMI, 32),
              fill=pal["muted"])
    _arrow(draw, W - MARGIN, H - 112, pal["accent"])
    img.save(out, quality=90)
    return out


def _render_cta_flash(headline: str, body: str, niche: Niche, pal: dict,
                      include_brand: bool, page: int, total: int, out: Path) -> Path:
    img = _card(pal["dark"], pal["dark2"])
    draw = ImageDraw.Draw(img)
    font, lines, size = _fit(draw, headline, FONT_BOLD, 80, CONTENT_W, 3, 60)
    y = 300
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=pal["cream"])
        y += int(size * 1.16)
    if body:
        bfont = _font(FONT_SEMI, 46)
        y += 56
        for line in _wrap_px(draw, body, bfont, CONTENT_W)[:4]:
            draw.text((MARGIN, y), line, font=bfont,
                      fill=_mix(pal["cream"], pal["dark"], 0.18))
            y += int(46 * 1.35)
    if include_brand:
        brand_line = niche.extra.get("brand_line") or f"{niche.product} · {niche.waitlist_url}"
        draw.text((MARGIN, H - 220), _strip_emoji(brand_line),
                  font=_font(FONT_SEMI, 38), fill=pal["accent"])
        hfont = _font(FONT_SEMI, 32)
        handle = _handle(niche)
        hw = draw.textlength(handle, font=hfont)
        draw.text((W - MARGIN - hw, H - 128), handle, font=hfont,
                  fill=_mix(pal["cream"], pal["dark"], 0.35))
    draw.text((MARGIN, H - 128), f"{page}/{total}", font=_font(FONT_SEMI, 32),
              fill=_mix(pal["cream"], pal["dark"], 0.45))
    img.save(out, quality=90)
    return out


# ── Flashcard content selection (the learning loop's write side) ─────────────────
def _parse_theme_value(v: str) -> tuple[str, str]:
    """'1-3 | how to ...' -> ('1-3', 'how to ...'); plain values -> ('', value)."""
    if "|" in (v or ""):
        age, _, phrase = v.partition("|")
        return age.strip(), phrase.strip()
    return "", (v or "").strip()


def _carousel_themes(niche: Niche) -> dict[str, tuple[str, str]]:
    """{theme_key: (age_band, search phrase)} from `carousel_themes`, falling back
    to the niche's YouTube `themes` so other niches keep working unchanged."""
    raw = niche.extra.get("carousel_themes") or niche.themes or {}
    return {k: _parse_theme_value(str(v)) for k, v in raw.items()}


def _ig_theme_data(data: dict) -> tuple[dict, dict]:
    """(themes, weights) for INSTAGRAM only. The per-platform split keeps units
    consistent (IG raw views vs YouTube search views); a stale winners.json
    (pre-split) falls back to the legacy mixed keys."""
    themes = (data.get("themes_by_platform") or {}).get("instagram")
    weights = (data.get("theme_weights_by_platform") or {}).get("instagram")
    if themes is None or weights is None:
        return data.get("themes") or {}, data.get("theme_weights") or {}
    return themes, weights


def _confident_carousel_weights(niche: Niche, keys) -> dict[str, float]:
    """winners.json INSTAGRAM theme weights restricted to carousel themes with enough
    samples (mirrors run_pipeline._confident_weights, parameterized by niche)."""
    themes, weights = _ig_theme_data(_load_json(run_pipeline.WINNERS_PATH, {}))
    out = {}
    for t, w in weights.items():
        if t in keys and themes.get(t, {}).get("n", 0) >= niche.min_sample_per_theme:
            try:
                out[t] = float(w)
            except (TypeError, ValueError):
                continue
    return out


def _pick_theme(niche: Niche, rng) -> tuple[str, str, str]:
    """(theme_key, age_band, phrase) — explore/exploit over measured carousel themes.

    This is what closes the loop for carousels: the theme is ASSIGNED to the LLM,
    weighted by winners.json medians once a theme has n >= min_sample_per_theme;
    explore_rate keeps every theme getting fresh tests."""
    themes = _carousel_themes(niche)
    if not themes:
        return "bedtime", "", "toddler bedtime"
    weights = _confident_carousel_weights(niche, themes.keys())
    # Exploit only once >=2 themes are trusted: with a single measured theme there is
    # nothing to compare against, and "exploit" would just hammer that one theme for
    # 80% of picks however weak it is — keep exploring until a real leader exists.
    if len(weights) >= 2 and rng.random() >= niche.explore_rate:
        keys = list(weights)
        key = rng.choices(keys, [max(weights[k], 0.1) for k in keys])[0]
    else:
        key = rng.choice(list(themes))
    age, phrase = themes[key]
    return key, age, phrase


def _pick_hook_type(rng) -> str:
    """Assign today's hook type: coverage first (every type measured HOOK_MIN_SAMPLE
    times, using only DISTRIBUTED posts' standings), then explore/exploit on median
    views. This is what actually fills the carousel_hooks standings with >1 arm."""
    stand = _load_json(run_pipeline.WINNERS_PATH, {}).get("carousel_hooks") or {}
    under = [h for h in HOOK_TYPES if (stand.get(h) or {}).get("n", 0) < HOOK_MIN_SAMPLE]
    if under:
        return rng.choice(under)
    if rng.random() < HOOK_EXPLORE_RATE:
        return rng.choice(list(HOOK_TYPES))
    weights = [max(float((stand.get(h) or {}).get("median_views", 0)), 0.5)
               for h in HOOK_TYPES]
    return rng.choices(list(HOOK_TYPES), weights)[0]


def _keyword_cta_allowed() -> bool:
    state = _load_json(ENGAGE_STATE, {})
    return bool(state.get("comments_scope_ok", True))


def _pick_engagement_cta(rng) -> str:
    pool = [(k, w) for k, w in ENGAGEMENT_CTAS
            if k != "comment_keyword" or _keyword_cta_allowed()]
    return rng.choices([k for k, _ in pool], [w for _, w in pool])[0]


def _recent_carousel_performance(limit: int = 2) -> list[dict]:
    rows = [r for r in run_pipeline.ledger.load()
            if r.get("finalized") and r.get("views") is not None
            and r.get("platform") == "instagram"]
    rows.sort(key=lambda r: r.get("measured_at") or r.get("posted_at") or "",
              reverse=True)
    return [{"title": r.get("title"), "theme": r.get("theme"),
             "views": r.get("views"), "likes": r.get("likes"),
             "hook_type": r.get("hook_type")} for r in rows[:limit]]


# ── Flashcard LLM writer ─────────────────────────────────────────────────────────
_ENGAGEMENT_RULES = {
    "save": ('cta.headline/body + the caption ending nudge SAVING this post for later, '
             'in fresh words (never the same phrasing twice).'),
    "share": ('cta.headline/body + the caption ending nudge SENDING this to another '
              'parent who needs it, in fresh warm words.'),
    "caption_bonus": ('the cta slide promises "2 bonus tips in the caption" (your own '
                      'wording) and the caption MUST actually contain 2 extra numbered '
                      'tips beyond the slides.'),
    "comment_keyword": ('the cta slide + caption invite readers to COMMENT one ALL-CAPS '
                        'keyword matching the topic (e.g. SLEEP) to get the full '
                        'checklist as a reply. Also return "keyword" (that single word) '
                        'and "bonus_content" (the plain-text checklist we will reply '
                        'with, <= 900 characters, no emojis needed).'),
}


def _flash_system(niche: Niche, include_brand: bool, engagement: str,
                  hook_type: str) -> str:
    brand_line = niche.extra.get("brand_line") or niche.product
    brand_rule = (
        f'- The LAST slide carries the soft brand line "{brand_line}" (we render it — '
        "don't put it in slides[]). The caption MAY include ONE soft plain-words "
        "sentence about the app if it fits the topic naturally; otherwise skip it. "
        "NO brand mention anywhere else."
        if include_brand else
        "- This post is 100% value: NO app/brand mention anywhere — not in slides, "
        "not in the caption.")
    return (
        f"{niche.brand_context}\n\n"
        "You write Instagram CAROUSELS for parents of kids aged 1-7, modeled on top "
        "parenting accounts (Big Little Feelings, Good Inside, Solid Starts): flat "
        "flashcard slides, ONE idea per slide, generous whitespace, zero fluff. This "
        "is VALUE content a parent screenshots — never marketing.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        ' "format": "listicle" | "do_instead" | "myth_truth" | "scripts",\n'
        f' "hook_type": "{hook_type}",\n'
        f' "headline": "<cover hook, <= 9 words, earns the swipe — MUST be a '
        f'{hook_type} hook: {HOOK_SPECS[hook_type]}>",\n'
        ' "cover_kicker": "<3-6 word audience eyebrow, e.g. FOR TIRED TODDLER PARENTS '
        'or FOR PARENTS OF 4-6 YEAR OLDS — match the assigned age band>",\n'
        ' "slides": [{"title": "<the point, <= 8 words>", "body": "<ONE concrete '
        'sentence, <= 18 words>"}, ... 4-7 items],\n'
        ' "cta": {"headline": "<e.g. Was this helpful?>", "body": "<1-2 short lines>"},\n'
        ' "caption": "<see CAPTION rules>",\n'
        ' "hashtags": ["#..", 3-5 niche tags]\n'
        "}\n\n"
        "Rules:\n"
        f"- HOOK TYPE IS ASSIGNED: the headline must be a {hook_type} hook "
        f"({HOOK_SPECS[hook_type]}) — do not fall back to a numbered listicle "
        "headline unless the assigned type is number_promise. The slide FORMAT may "
        "still be a listicle; the headline is what must match the assigned hook.\n"
        "- Slides deliver EXACTLY what the headline promises. Real, specific, usable — "
        'never vague filler like "be patient" or "stay consistent".\n'
        "- NO brand/app names and NO emojis in headline, cover_kicker, slides or cta "
        "(the renderer can't draw emoji). Emojis are allowed in the caption only.\n"
        "- Tailor advice, examples and language to the assigned age band.\n"
        "- CAPTION: line 1 = a scroll-stopping hook in DIFFERENT words than the "
        "headline — a specific pain, confession or stat a parent feels ('It's 9pm "
        "and you're still lying on their floor'), NEVER generic marketing voice "
        "('Transform bedtime...'). Blank line; 2-3 sentences of real value or "
        "empathy; blank line; the engagement ask below.\n"
        "- Hashtags go ONLY in the hashtags field — never inside the caption text.\n"
        "- NEVER invite readers to comment a keyword unless the ENGAGEMENT "
        "instruction below explicitly says so.\n"
        f"- ENGAGEMENT: {_ENGAGEMENT_RULES[engagement]}\n"
        f"{brand_rule}")


def _flash_user(niche: Niche, theme_key: str, age_band: str, phrase: str,
                avoid_titles: list[str]) -> str:
    themes = _carousel_themes(niche)
    themes_block = "\n".join(
        f'- {k} (ages {a or "1-7"}): parents search "{p}"' for k, (a, p) in themes.items())
    winners = _load_json(run_pipeline.WINNERS_PATH, {})
    _, ig_weights = _ig_theme_data(winners)  # IG-only numbers, same units as the KPI
    weights = {k: v for k, v in ig_weights.items() if k in themes}
    hooks = winners.get("carousel_hooks") or {}
    perf = _recent_carousel_performance()
    avoid = "\n".join(f"- {t}" for t in avoid_titles[-15:]) or "(none yet)"
    return (
        f'Assigned theme: {theme_key} — parents search "{phrase}" '
        f'(age band: {age_band or "1-7"}). Write for THIS theme.\n\n'
        f"All carousel themes for context:\n{themes_block}\n\n"
        "Theme weights so far (median views/post; WEAK signal below n=4 — favor "
        "leaders only slightly):\n"
        f"{json.dumps(weights, indent=2) if weights else '(no measured data yet)'}\n\n"
        "Carousel hook-type standings so far (context only — today's hook type is "
        "assigned in the system prompt):\n"
        f"{json.dumps(hooks, indent=2) if hooks else '(none yet)'}\n\n"
        "How the last measured carousels performed:\n"
        f"{json.dumps(perf, indent=2) if perf else '(nothing measured yet)'}\n\n"
        f"Headlines already used — do NOT repeat or paraphrase:\n{avoid}\n\n"
        "Write today's carousel as JSON only.")


def _clean_caption(caption: str, engagement: str) -> str:
    """Drop hashtag-only lines (tags live in the hashtags field; the publisher appends
    them once) and, on non-keyword posts, any leaked 'comment WORD' ask — a promise
    nothing would ever reply to."""
    out = []
    for line in caption.splitlines():
        stripped = line.strip()
        if stripped and all(w.startswith("#") for w in stripped.split()):
            continue
        if (engagement != "comment_keyword" and
                re.search(r'\bcomment\b.{0,12}["\'«]?[A-Z]{2,}', stripped)):
            continue
        out.append(line)
    return "\n".join(out).strip()


def _hook_complies(hook_type: str | None, headline: str) -> bool:
    """number_promise headlines lead with a digit; the other three must not."""
    if hook_type not in HOOK_TYPES or not headline:
        return True
    digit_lead = headline[:1].isdigit()
    return digit_lead if hook_type == "number_promise" else not digit_lead


def _actual_hook_type(hook_type: str | None, data: dict, headline: str) -> str:
    if hook_type in HOOK_TYPES:
        return hook_type if _hook_complies(hook_type, headline) else "number_promise"
    reported = data.get("hook_type")
    return reported if reported in HOOK_TYPES else "curiosity_gap"


def _validate_flash(data: dict, theme_key: str, engagement: str,
                    hook_type: str | None = None) -> dict | None:
    """Normalize/clamp the LLM JSON; None → template fallback."""
    headline = _strip_emoji(str(data.get("headline") or ""))
    raw_slides = data.get("slides") or []
    slides = []
    for s in raw_slides:
        if isinstance(s, dict):
            title = _strip_emoji(str(s.get("title") or ""))
            body = _strip_emoji(str(s.get("body") or ""))
        else:
            title, body = _strip_emoji(str(s)), ""
        if title:
            slides.append({"title": title, "body": body})
    if not headline or len(slides) < 4:
        return None
    slides = slides[:7]                      # cover + 7 + CTA = 9 <= IG max 10
    cta = data.get("cta") or {}
    if not isinstance(cta, dict):
        cta = {}
    kw = bonus = None
    if engagement == "comment_keyword":
        kw = re.sub(r"[^A-Za-z]", "", str(data.get("keyword") or "")).upper()
        bonus = str(data.get("bonus_content") or "").strip()[:950]
        if not (kw and bonus):
            # never promise a reply we don't have the payload for
            engagement, kw, bonus = "save", None, None
    out = {
        "theme": theme_key,                  # snap — the theme was assigned in code
        "format": (data.get("format") if data.get("format") in CAROUSEL_FORMATS
                   else "listicle"),
        # snap to the ASSIGNED arm — but if the LLM ignored a non-numeric assignment
        # and led with a digit anyway, the ledger records what actually shipped
        # (number_promise), so the standings never credit the wrong arm.
        "hook_type": _actual_hook_type(hook_type, data, headline),
        "headline": headline,
        "cover_kicker": _strip_emoji(str(data.get("cover_kicker") or "")),
        "slides": slides,
        "cta_headline": _strip_emoji(str(cta.get("headline") or "Was this helpful?")),
        "cta_body": _strip_emoji(str(cta.get("body") or "Save it for the next hard day.")),
        "caption": _clean_caption(str(data.get("caption") or headline), engagement),
        "hashtags": [h.strip() for h in (data.get("hashtags") or [])
                     if h and str(h).strip().startswith("#")][:5],
        "engagement_cta": engagement,
    }
    if kw:
        out["keyword"] = kw
        out["bonus_content"] = bonus
    return out


def _llm_flashcard(niche: Niche, theme_key: str, age_band: str, phrase: str,
                   include_brand: bool, engagement: str, hook_type: str,
                   avoid_titles: list[str]) -> dict | None:
    try:
        import ghostwriter
        client = ghostwriter._client()
    except Exception:
        return None
    import os
    deployment = (os.environ.get("NINNITALES_CHAT_DEPLOYMENT")
                  or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT"))
    messages = [
        {"role": "system",
         "content": _flash_system(niche, include_brand, engagement, hook_type)},
        {"role": "user",
         "content": _flash_user(niche, theme_key, age_band, phrase, avoid_titles)}]
    # Up to 2 attempts: GPT's default habit is a numbered listicle headline, so a
    # non-numeric hook assignment gets one corrective retry before we accept the
    # result (and _actual_hook_type re-labels it if it still disobeyed).
    for attempt in (1, 2):
        try:
            resp = client.chat.completions.create(
                model=deployment, temperature=1.0,
                response_format={"type": "json_object"}, messages=messages)
            choice = resp.choices[0]
            if choice.finish_reason == "content_filter" or not choice.message.content:
                return None
            data = json.loads(choice.message.content)
        except Exception as e:
            print(f"  ⚠️  carousel LLM failed ({e}) — using template.")
            return None
        headline = _strip_emoji(str(data.get("headline") or ""))
        if attempt == 1 and not _hook_complies(hook_type, headline):
            print(f"  ↻ headline {headline!r} isn't a {hook_type} hook — one retry.")
            messages.append({"role": "assistant", "content": choice.message.content})
            messages.append({"role": "user", "content":
                             f'The headline must be a {hook_type} hook: '
                             f'{HOOK_SPECS[hook_type]} Rewrite the JSON with a '
                             'compliant headline (keep the same theme).'})
            continue
        return _validate_flash(data, theme_key, engagement, hook_type)
    return None


# Canned value carousels so the format ALWAYS produces something when the LLM is
# down/filtered. No branded slide; brand appears only via the rendered brand line.
_FLASH_TEMPLATES = [
    {
        "theme": "sleep_fast", "format": "listicle", "hook_type": "number_promise",
        "headline": "5 tricks that get a toddler asleep in 20 minutes",
        "cover_kicker": "FOR TIRED TODDLER PARENTS",
        "slides": [
            {"title": "Start the wind-down an hour early",
             "body": "Dim the lights so their body clock catches on before you say the word bed."},
            {"title": "Same three steps every night",
             "body": "Bath, book, bed — predictability is what actually settles them."},
            {"title": "Keep the room cool and dark",
             "body": "Around 68F / 20C is the sweet spot for little sleepers."},
            {"title": "A familiar voice beats a screen",
             "body": "A story in a voice they know calms faster than any app or show."},
            {"title": "Leave before they're fully asleep",
             "body": "Drowsy-but-awake teaches them to do the last step alone."},
        ],
    },
    {
        "theme": "tantrums", "format": "do_instead", "hook_type": "mistake",
        "headline": "You're handling tantrums backwards",
        "cover_kicker": "FOR PARENTS OF 1-4 YEAR OLDS",
        "slides": [
            {"title": "Don't reason mid-meltdown",
             "body": "A flooded brain can't hear logic — wait for the storm to pass."},
            {"title": "Name the feeling first",
             "body": "You're SO mad the tower fell — being seen shrinks the tantrum."},
            {"title": "Stay boring, stay close",
             "body": "Big reactions feed the fire; calm presence starves it."},
            {"title": "Offer two choices after",
             "body": "Red cup or blue cup? Control is what they were really after."},
        ],
    },
    {
        "theme": "picky_eating", "format": "listicle", "hook_type": "curiosity_gap",
        "headline": "4 picky-eater tricks pediatric dietitians swear by",
        "cover_kicker": "FOR PARENTS OF PICKY EATERS",
        "slides": [
            {"title": "Serve one safe food every meal",
             "body": "Something they always eat takes the pressure off the new stuff."},
            {"title": "Let them touch, not taste",
             "body": "Exposure counts even without a bite — it can take 15 tries."},
            {"title": "You decide what, they decide how much",
             "body": "The division of responsibility ends most table battles."},
            {"title": "Make food boring, not a show",
             "body": "No bribes, no applause — pressure in any direction backfires."},
        ],
    },
]


def _template_flashcard(niche: Niche, rng, include_brand: bool,
                        avoid_titles: list[str]) -> dict:
    avoid = {" ".join(t.lower().split()) for t in avoid_titles}
    pool = [t for t in _FLASH_TEMPLATES
            if " ".join(t["headline"].lower().split()) not in avoid] or _FLASH_TEMPLATES
    t = dict(rng.choice(pool))
    caption = rng.choice([
        "Bedtime, meltdowns, dinner battles — pick your fighter. This one's for the "
        "hard evenings.\n\nSave this for the next one. Which tip are you trying first?",
        "Some days it feels like nothing works. These do, more often than not.\n\n"
        "Send this to a parent in the trenches. What would you add?",
    ])
    if include_brand:
        caption += f"\n\n🌙 More gentle ideas → {niche.waitlist_url}"
    t.update({
        "cta_headline": "Was this helpful?",
        "cta_body": "Save it for the next hard day. Send it to a parent who needs it.",
        "caption": caption,
        "hashtags": niche.default_hashtags[:5],
        "engagement_cta": "save",
    })
    return t


# ── Legacy LLM/template/renderers (photo/anime path — other accounts + A/Bs) ─────
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
              "hook, <8 words>\", \"cover_scene\":\"<a short VISUAL description for a photo "
              "of a tired parent in a messy home that matches the headline's feeling — e.g. "
              "'sitting on the floor of a toy-strewn playroom rubbing their eyes at night'; "
              "a realistic bedtime/parenting moment, NO child in it>\", "
              "\"slides\":[\"slide 2 tip\",\"slide 3 tip (the NinniTales "
              "one, plain words)\",\"slide 4 tip\",\"slide 5 tip\"], "
              "\"slide_scenes\":[\"<short VISUAL for slide 2 matching its tip — the SAME "
              "tired parent doing a small real action in a lived-in home, NO child, e.g. "
              "'dimming a bedside lamp in a cozy messy bedroom at night'>\",\"<visual for "
              "slide 3>\",\"<visual for slide 4>\",\"<visual for slide 5>\"], "
              "\"caption\":\"<IG caption>\", "
              "\"hashtags\":[\"#..\",...]}. The slides are short, real, scannable bedtime "
              "advice; each slide_scenes entry describes one calm, relevant parenting/home "
              "moment (a tired parent, NO child — image models refuse depicted minors) that "
              "illustrates that slide's tip. slide_scenes MUST have the same length as "
              "slides. NO emojis in the headline.\n"
              "CAPTION rules — it must be UNIQUE every day, never a template: first line = a "
              "fresh scroll-stopping hook (a feeling or pain the parent recognizes, different "
              "wording from the headline); middle = 1-2 sentences of real value or empathy; "
              "end = a save nudge in YOUR OWN fresh words (vary it: 'save this for tonight', "
              "'send this to a tired parent', 'try step 3 tonight'...) plus ONE gentle "
              "question to invite a comment. Soft mention of the app at most — never a pitch.")
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
        "slide_scenes": [
            "dimming a warm bedside lamp in a cozy messy bedroom at dusk, tired but tender",
            "sitting on the edge of an unmade bed holding a phone playing a bedtime story, "
            "an open storybook on a blanket beside them",
            "pulling a curtain closed in a dark, cool, tidy bedroom at night, moonlight "
            "spilling in, worn out but calm",
            "tidying a small stack of picture books in a snug lamplit reading nook",
        ],
        "caption": rng.choice([
            "Save this for tonight's bedtime — and if bedtime is a battle at yours, "
            "which step will you try first?",
            "Send this to a parent running on no sleep. Which of these do you already do?",
            "Try step 3 tonight and tell me if it worked. What's your toughest bedtime "
            "moment?",
        ]) + f" 🌙 More gentle-bedtime ideas → {niche.waitlist_url}",
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


def _veil(img: Image.Image, alpha: int = 150) -> None:
    """Darken the whole image uniformly so centered white tip text stays legible over any
    photo background."""
    overlay = Image.new("RGB", img.size, (12, 8, 28))
    mask = Image.new("L", img.size, alpha)
    img.paste(overlay, (0, 0), mask)


def _render_slide(text: str, idx: int, total: int, scene: str, niche: Niche,
                  slot_index: int, out: Path) -> Path:
    img = _scene_image(niche, scene, slot_index)
    _veil(img)
    draw = ImageDraw.Draw(img)
    font = _font(FONT_BOLD, 60)
    wrap_at = 26
    lines = textwrap.wrap(text, width=wrap_at) or [text]
    line_h = int(60 * 1.3)
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


def _scene_image(niche: Niche, scene: str, slot_index: int):
    """The background for ANY slide (cover or value). `carousel_cover_style: realistic`
    (niche) → the photoreal, consistent NinniTales parent (mom/dad, chosen by slot_index so
    it's the SAME parent across every slide of this carousel) dropped into `scene` via the
    locked character reference; otherwise the cozy-anime pin background. Both cover-crop to
    W x H and degrade to a gradient if the image model is unavailable/slow/filtered."""
    from formats import pin as pin_fmt

    style = niche.extra.get("carousel_cover_style", "anime")
    if style == "realistic":
        import characters
        if characters.available():
            character = "mom" if slot_index % 2 == 0 else "dad"
            prompt = scene or characters.FALLBACK_SCENES[
                slot_index % len(characters.FALLBACK_SCENES)]
            return characters.scene(character, prompt, W, H)
    return pin_fmt._background(scene or pin_fmt.SCENES[slot_index % len(pin_fmt.SCENES)],
                              W, H)


def _render_cover(headline: str, cover_scene: str, niche: Niche, slot_index: int,
                  total: int, out: Path) -> Path:
    """Slide 1 — the swipe-decider: the cover image (realistic parent or anime) with the
    headline overlaid and a top scrim for legibility."""
    from formats import pin as pin_fmt

    img = _scene_image(niche, cover_scene, slot_index)
    pin_fmt._scrim(img, top=True)
    draw = ImageDraw.Draw(img)
    font = _font(FONT_BOLD, 88)
    lines = textwrap.wrap(headline, width=18) or [headline]
    y = 100
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text(((W - w) // 2 + 3, y + 3), line, font=font, fill=(0, 0, 0))
        draw.text(((W - w) // 2, y), line, font=font, fill=(255, 255, 255))
        y += int(88 * 1.28)
    small = _font(FONT_SEMI, 40)
    draw.text((60, H - 90), f"1/{total}", font=small, fill=(255, 255, 255))
    brand = "NinniTales"
    bw = draw.textlength(brand, font=small)
    draw.text((W - bw - 60, H - 90), brand, font=small, fill=(255, 235, 180))
    img.save(out)
    return out


class Carousel:
    name = "carousel"
    produces = CAROUSEL

    def build(self, niche: Niche, ctx: BuildContext) -> Asset | None:
        if niche.extra.get("carousel_style") == "flashcard":
            return self._build_flashcard(niche, ctx)
        return self._build_legacy(niche, ctx)

    # ── flashcard path (flat value cards + photo-library cover) ──────────────
    def _build_flashcard(self, niche: Niche, ctx: BuildContext) -> Asset | None:
        rng = ctx.rng
        theme_key, age_band, phrase = _pick_theme(niche, rng)
        include_brand = rng.random() >= (1 / 3)   # ~1-in-3 posts are 100% brand-free
        engagement = _pick_engagement_cta(rng)
        hook_type = _pick_hook_type(rng)
        data = (_llm_flashcard(niche, theme_key, age_band, phrase, include_brand,
                               engagement, hook_type, ctx.avoid_titles)
                or _template_flashcard(niche, rng, include_brand, ctx.avoid_titles))
        engagement = data.get("engagement_cta", "save")
        theme_key = data.get("theme") or theme_key   # templates carry their own theme
        pal = _palette(niche)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = run_pipeline.QUEUE_DIR / f"carousel_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

        slides = data["slides"]
        total = len(slides) + 2               # cover + points + CTA
        numbered = data.get("format") == "listicle"
        print(f"  🗂  flashcard carousel: {data['headline']!r} (theme={theme_key}, "
              f"hook={data.get('hook_type')}, cta={engagement}, "
              f"brand={'on' if include_brand else 'off'})")

        cover_bg = _library_cover(theme_key, phrase, age_band, rng)
        paths = [_render_cover_flash(data["headline"], data.get("cover_kicker", ""),
                                     niche, pal, cover_bg, out_dir / "slide_1.jpg")]
        for i, s in enumerate(slides, 1):
            paths.append(_render_point_flash(
                i, s["title"], s.get("body", ""), i + 1, total, pal, numbered,
                out_dir / f"slide_{i + 1}.jpg"))
        paths.append(_render_cta_flash(
            data.get("cta_headline", "Was this helpful?"),
            data.get("cta_body", ""), niche, pal, include_brand, total, total,
            out_dir / f"slide_{total}.jpg"))

        meta = {"title": data["headline"],
                "description": data.get("caption") or data["headline"],
                "hashtags": data.get("hashtags") or niche.default_hashtags[:5],
                "tags": niche.tags,
                "hook_type": data.get("hook_type"),
                "carousel_format": data.get("format"),
                "engagement_cta": engagement}
        if engagement == "comment_keyword":
            meta["keyword"] = data.get("keyword")
            meta["bonus_content"] = data.get("bonus_content")
        return Asset(kind=CAROUSEL, paths=paths, theme=theme_key,
                     source="carousel", meta=meta)

    # ── legacy path (AI photo/anime background on every slide) ───────────────
    def _build_legacy(self, niche: Niche, ctx: BuildContext) -> Asset | None:
        data = _llm_carousel(niche, ctx.avoid_titles) or _template_carousel(niche, ctx.rng)
        headline = data["headline"]
        slides_text = [headline] + list(data["slides"])
        slide_scenes = list(data.get("slide_scenes") or [])
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = run_pipeline.QUEUE_DIR / f"carousel_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        total = len(slides_text)
        for i, text in enumerate(slides_text, 1):
            if i == 1:
                p = _render_cover(text, data.get("cover_scene", ""), niche,
                                  ctx.slot_index, total, out=out_dir / "slide_1.png")
            else:
                # slides_text[0] is the headline, so value slide i maps to slide_scenes[i-2]
                scene = slide_scenes[i - 2] if i - 2 < len(slide_scenes) else ""
                p = _render_slide(text, i, total, scene, niche, ctx.slot_index,
                                  out=out_dir / f"slide_{i}.png")
            paths.append(p)
        caption = data.get("caption") or headline
        return Asset(kind=CAROUSEL, paths=paths, theme=data.get("theme", "bedtime"),
                     source="carousel",
                     meta={"title": headline, "description": caption,
                           "hashtags": data.get("hashtags", niche.default_hashtags),
                           "tags": niche.tags})


register(Carousel())
