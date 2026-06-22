"""
generate_hook.py — make an original cozy-anime hook clip for a NinniTales Short.

No scraping, no copyright risk, on-brand, fully automated. Pipeline:

  GPT (chat)   → writes 1 emotional hook line + a matching cozy-anime image prompt
  gpt-image-1  → renders a vertical anime scene (parent + 2-8yo child, bedtime)
  PIL          → composites the bold caption as a CRISP STATIC overlay (Anton font)
  ffmpeg       → gentle Ken Burns zoom on the image BEHIND the static text
                 → 3.5s 1080x1920 hook clip (silent; stitch_cta extends the CTA's
                   own music back over the hook so the whole Short has one track)

Config (env vars; falls back to the AssuredReferral Azure deployment):
  AZURE_OPENAI_API_KEY / _ENDPOINT / _API_VERSION   (required, shared)
  NINNITALES_CHAT_DEPLOYMENT   (default: AZURE_OPENAI_CHAT_DEPLOYMENT)
  NINNITALES_IMAGE_DEPLOYMENT  (default: AZURE_OPENAI_IMAGE_DEPLOYMENT)
  NINNITALES_IMAGE_QUALITY     (default: high)   gpt-image-1: low|medium|high|auto
  NINNITALES_IMAGE_SIZE        (default: 1024x1536)

To get the "better image" model: create a full gpt-image-1 deployment in Azure
and set NINNITALES_IMAGE_DEPLOYMENT=gpt-image-1 (the repo default is the mini).
"""

import base64
import csv
import io
import json
import os
import random
import re
import subprocess
from pathlib import Path

from openai import AzureOpenAI
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
# Poppins (rounded geometric sans) to MATCH the CTA's caption font. Was Anton
# (tall condensed all-caps) which clashed with the CTA's friendly look.
FONT_PATH = HERE / "assets" / "fonts" / "Poppins-Bold.ttf"
BADGE_FONT_PATH = HERE / "assets" / "fonts" / "Poppins-SemiBold.ttf"
# Proven viral short-video hook FORMATS (templates with placeholders). We don't
# invent hooks from scratch — we pick a format here and rewrite it for NinniTales.
HOOK_FORMATS_FILE = HERE / "hooks" / "hook_formats.csv"

W, H = 1080, 1920
HOOK_SECONDS = 3.5
FPS = 30

# The brand look. One line to change the whole visual identity.
ART_STYLE = (
    "cozy anime illustration, Studio Ghibli inspired, soft painterly lighting, "
    "warm bedtime color palette, gentle and emotional, wholesome and family-friendly, "
    "hand-drawn feel, highly detailed, cinematic vertical composition"
)

# IMPORTANT — filter safety: Azure/OpenAI image models refuse to depict young
# children, especially in bedroom/bed scenes, and Azure's text filter false-trips
# on "child + bed" phrasing. So we EVOKE the bedtime emotion through the
# environment and the parent, and never ask for a detailed child in frame.
HOOK_SYSTEM = """You write scroll-stopping opening hooks for NinniTales — an app where
a parent records 90 seconds of their voice once, and the app then narrates bedtime
stories in the parent's OWN voice so their young child can fall asleep to it, anywhere.
The buyer is the PARENT; the emotional lever is the longing of being away and the
warmth of a familiar voice at night.

Rotate across these emotional angles for freshness:
- a parent away (work trip, late shift, long commute) at goodnight time
- the comfort of a familiar voice reading a story at night
- the warm moment a story begins and the room settles
- record once, read every night
- bedtime that feels like the parent is right there, even from far away
- the BEDTIME BATTLE: a cranky, overtired kid who won't settle and an exhausted,
  frustrated parent at the end of their rope — until the familiar voice finally calms
  the room (the relatable pain, then the relief NinniTales brings)
- the "one more story" stand-off and the worn-out parent who just needs bedtime to end

STRICT CONTENT RULES (a safety filter will block violations):
- Keep everything wholesome and family-friendly.
- For image_prompt, EVOKE bedtime through the ENVIRONMENT and the PARENT, never a
  child's body or face. Good subjects: a cozy nursery with a soft glowing nightlight,
  a neatly made small bed with a teddy bear, a warm smart speaker glowing on a shelf,
  a starry window, a storybook on a blanket, a parent's silhouette or hands, a parent
  at an airport/desk at night looking at a phone. At most a tiny distant silhouette.
- For the BEDTIME BATTLE angle, convey the chaos and the parent's frustration through
  the ENVIRONMENT and the PARENT only: an exhausted parent slumped against the nursery
  door or rubbing their temples, toys and storybooks scattered across the floor, a
  half-collapsed pillow fort, tangled blankets, a clock reading very late, a parent
  sitting on the floor in a dim hallway with head in hands. Keep it warm and wholesome,
  never distressing — tired, not scary. Still NO child's body or face.
- Do NOT describe a child in bed, a child's body, faces of minors, or anyone undressed.

Return STRICT JSON, no markdown:
{
  "hook_text": "<= 7 words, emotional, scroll-stopping, NO emojis, NO hashtags, NO quotes",
  "image_prompt": "a vivid, wholesome scene per the rules above. Keep the UPPER THIRD of
  the frame calm/simple so caption text is readable. Do NOT mention any text or words
  appearing in the image."
}"""


def _client(api_version: str | None = None) -> AzureOpenAI:
    """Shared Azure client (AssuredReferral resource) — used for the GPT hook copy."""
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    version = api_version or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    if not key or not endpoint:
        raise SystemExit("❌ AZURE_OPENAI_API_KEY / _ENDPOINT not set "
                         "(source the AssuredReferral .env or export them).")
    return AzureOpenAI(api_key=key, azure_endpoint=endpoint, api_version=version)


def _image_creds() -> tuple[str, str]:
    """Resolve (v1_base_url, api_key) for the image model.

    NinniTales' image model lives in its OWN Microsoft Foundry project — a modern
    `*.services.ai.azure.com` resource that exposes only the OpenAI **v1** surface
    (`/openai/v1/...`), NOT the classic `/openai/deployments/...` path. Prefer the
    NINNITALES_IMAGE_* credentials; fall back to the shared Azure resource.
    """
    key = (os.environ.get("NINNITALES_IMAGE_API_KEY")
           or os.environ.get("AZURE_OPENAI_API_KEY"))
    endpoint = (os.environ.get("NINNITALES_IMAGE_ENDPOINT")
                or os.environ.get("AZURE_OPENAI_ENDPOINT"))
    if not key or not endpoint:
        raise SystemExit("❌ NINNITALES_IMAGE_API_KEY / NINNITALES_IMAGE_ENDPOINT "
                         "(or the shared AZURE_OPENAI_* fallback) not set.")
    # Foundry's overview page gives a project URL like
    # https://<res>.services.ai.azure.com/api/projects/<name>. Keep only the host.
    m = re.match(r"(https://[^/]+)", endpoint.strip())
    host = m.group(1) if m else endpoint.rstrip("/")
    return f"{host}/openai/v1", key


def _load_hook_formats() -> list[tuple[str, str]]:
    """Read viral hook-format templates as (category, hook) from hook_formats.csv."""
    if not HOOK_FORMATS_FILE.exists():
        return []
    formats = []
    with HOOK_FORMATS_FILE.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            h = (row.get("hook") or "").strip()
            if h:
                formats.append(((row.get("category") or "").strip(), h))
    return formats


def _user_prompt(formats: list[tuple[str, str]]) -> str:
    """Build the per-call instruction. If we have viral formats, adapt one; else freestyle.

    We over-sample the niche-native "Parenting" formats so generated hooks feel native
    to the audience, then mix in general viral structures for variety.
    """
    if not formats:
        return "Write one fresh hook for today's Short. JSON only."
    parenting = [h for c, h in formats if c.lower() == "parenting"]
    general = [h for c, h in formats if c.lower() != "parenting"]
    sample = (random.sample(parenting, min(6, len(parenting)))
              + random.sample(general, min(6, len(general))))
    random.shuffle(sample)
    block = "\n".join(f"- {s}" for s in sample)
    return (
        "Here are proven viral short-video hook FORMATS (templates; placeholders like "
        "(topic)/(result)/(X5) are slots to fill):\n"
        f"{block}\n\n"
        "Choose the ONE format that best fits a NinniTales bedtime / parent's-voice angle, "
        "then rewrite it into our hook by filling the slots with our context (record your "
        "voice once; bedtime stories in your own voice; being away at night; a familiar "
        "voice as comfort). KEEP the format's structure and punch — don't invent a new "
        "shape. If none fit, use a curiosity or relatable structure. Then write a matching "
        "image_prompt per the rules. JSON only."
    )


def write_hook_copy(attempts: int = 5) -> dict:
    """GPT writes today's hook line + image prompt. Returns {hook_text, image_prompt}.

    The hook is modeled on a proven viral format (hook_formats.csv) rewritten for
    NinniTales — not invented from scratch. Azure's text filter occasionally
    false-trips on bedtime/child phrasing and returns no content
    (finish_reason=content_filter); output varies with temperature, so we retry.
    """
    client = _client()
    deployment = (os.environ.get("NINNITALES_CHAT_DEPLOYMENT")
                  or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT"))
    formats = _load_hook_formats()
    for i in range(attempts):
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": HOOK_SYSTEM},
                {"role": "user", "content": _user_prompt(formats)},
            ],
            temperature=1.0,
            response_format={"type": "json_object"},
        )
        choice = resp.choices[0]
        if choice.finish_reason == "content_filter" or not choice.message.content:
            print(f"  ⚠️  hook copy filtered (attempt {i + 1}/{attempts}), retrying...")
            continue
        data = json.loads(choice.message.content)
        if data.get("hook_text") and data.get("image_prompt"):
            return data
    raise RuntimeError("hook copy blocked by content filter after retries — "
                       "soften HOOK_SYSTEM wording or lower the deployment's filter severity.")


def generate_image(image_prompt: str, attempts: int = 2) -> bytes:
    """Render a cozy-anime vertical scene with gpt-image-2. Returns PNG bytes.

    Calls the Foundry resource's OpenAI v1 images endpoint directly via the `api-key`
    header (the only surface this resource exposes). Image models can refuse a prompt
    outright (safety); we retry once, then raise so the run skips this hook.
    """
    import ssl
    import urllib.error
    import urllib.request

    import certifi

    ctx = ssl.create_default_context(cafile=certifi.where())
    base_url, key = _image_creds()
    deployment = (os.environ.get("NINNITALES_IMAGE_DEPLOYMENT")
                  or os.environ.get("AZURE_OPENAI_IMAGE_DEPLOYMENT"))
    quality = os.environ.get("NINNITALES_IMAGE_QUALITY", "high")
    size = os.environ.get("NINNITALES_IMAGE_SIZE", "1024x1536")
    print(f"  image: deployment={deployment} quality={quality} size={size}")

    url = f"{base_url}/images/generations"
    payload = json.dumps({
        "model": deployment,
        "prompt": f"{ART_STYLE}. Scene: {image_prompt}",
        "size": size,
        "quality": quality,
        "n": 1,
    }).encode()

    last_err = None
    for i in range(attempts):
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json", "api-key": key},
        )
        try:
            with urllib.request.urlopen(req, timeout=180, context=ctx) as resp:
                data = json.loads(resp.read())
            return base64.b64decode(data["data"][0]["b64_json"])
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            last_err = f"HTTP {e.code}: {body[:200]}"
            print(f"  ⚠️  image call failed (attempt {i + 1}/{attempts}): {last_err}")
            if e.code in (401, 403, 404):  # auth/path errors won't fix on retry
                break
    raise RuntimeError(f"image generation failed: {last_err}")


def _cover_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to cover w x h then center-crop (full-bleed, no bars)."""
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = round(h * src_ratio)
    else:
        new_w = w
        new_h = round(w / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img.crop((left, top, left + w, top + h))


def _wrap_lines(text: str, font: ImageFont.FreeTypeFont, max_w: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Greedy word-wrap to fit max_w pixels."""
    words = text.split()
    lines, cur = [], ""
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


# Keep on-screen captions to glyphs the Anton display font can render — strip
# emojis/symbols (titles carry 😴🌙 etc. that would render as tofu boxes).
_CAPTION_STRIP = re.compile(r"[^A-Za-z0-9 '\"?!.,:;()&%/+-]+")


def clean_caption(text: str) -> str:
    """Drop characters the display font can't draw; collapse whitespace."""
    return re.sub(r"\s+", " ", _CAPTION_STRIP.sub("", text)).strip()


def _text_overlay(hook_text: str) -> Image.Image:
    """RGBA 1080x1920 overlay: bottom scrim + Poppins caption with a SOFT shadow.

    Styled to match the CTA clip: rounded font, natural (not all-caps) case, white
    fill with a gentle drop shadow instead of a hard outline, anchored at the bottom.
    """
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Bottom scrim: fades transparent(top)→dark(bottom) so text reads over any image.
    scrim_h = int(H * 0.46)
    scrim = Image.new("L", (1, scrim_h))
    for y in range(scrim_h):
        scrim.putpixel((0, y), int(170 * (y / scrim_h)))  # darker toward the bottom
    scrim = scrim.resize((W, scrim_h))
    black = Image.new("RGBA", (W, scrim_h), (0, 0, 0, 255))
    black.putalpha(scrim)
    overlay.alpha_composite(black, (0, H - scrim_h))

    margin = 80
    max_w = W - 2 * margin
    size = 120  # Poppins is wider than Anton — start a touch smaller
    text = hook_text.strip()  # keep natural case (CTA isn't all-caps)
    # Shrink font until the longest line fits and we have <= 4 lines.
    while size > 52:
        font = ImageFont.truetype(str(FONT_PATH), size)
        lines = _wrap_lines(text, font, max_w, draw)
        if len(lines) <= 4 and all(draw.textlength(ln, font=font) <= max_w for ln in lines):
            break
        size -= 5
    font = ImageFont.truetype(str(FONT_PATH), size)
    lines = _wrap_lines(text, font, max_w, draw)

    # Bottom-anchor the block, clearing the Shorts bottom UI (handle/title bar).
    line_h = int(size * 1.2)
    bottom_margin = int(H * 0.16)
    y0 = H - bottom_margin - line_h * len(lines)

    # Soft drop shadow: dark text on its own layer, blurred, nudged down-right.
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    y = y0
    for line in lines:
        x = (W - draw.textlength(line, font=font)) / 2
        sdraw.text((x, y), line, font=font, fill=(0, 0, 0, 200))
        y += line_h
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    overlay.alpha_composite(shadow, (3, 8))

    # White text on top, with a thin stroke just for crisp edges over bright spots.
    y = y0
    for line in lines:
        x = (W - draw.textlength(line, font=font)) / 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=3, stroke_fill=(0, 0, 0, 140))
        y += line_h
    return overlay


def _badge_overlay() -> Image.Image:
    """Top pill nudging viewers to open the description for the full list."""
    label = "Full list in description"
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    font = ImageFont.truetype(str(BADGE_FONT_PATH), 50)
    tw = d.textlength(label, font=font)
    asc, desc = font.getmetrics()
    th = asc + desc
    pad_x, pad_y, gap, chev = 42, 22, 18, 30
    bw = tw + 2 * pad_x + gap + chev
    bh = th + 2 * pad_y
    x = (W - bw) // 2
    y = int(H * 0.055)
    d.rounded_rectangle([x, y, x + bw, y + bh], radius=bh // 2, fill=(20, 18, 30, 190))
    tx, ty = x + pad_x, y + pad_y
    d.text((tx, ty), label, font=font, fill=(255, 255, 255, 255))
    # down-chevron after the text
    cx, cy = tx + tw + gap, ty + th * 0.30
    d.line([(cx, cy), (cx + chev / 2, cy + chev * 0.55), (cx + chev, cy)],
           fill=(255, 255, 255, 255), width=8, joint="curve")
    return ov


def _ken_burns(base_png: Path, text_png: Path, out_path: Path) -> Path:
    """Gentle zoom on the image behind the static text overlay → silent hook mp4."""
    frames = int(HOOK_SECONDS * FPS)
    filt = (
        f"[0:v]scale={W*2}:{H*2},"
        f"zoompan=z='min(zoom+0.0009,1.12)':d={frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}[bg];"
        f"[bg][1:v]overlay=0:0,format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(base_png),
        "-loop", "1", "-i", str(text_png),
        "-filter_complex", filt,
        "-map", "[v]", "-t", f"{HOOK_SECONDS}", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


def generate_hook(out_path: Path, work_dir: Path | None = None,
                  caption_override: str | None = None) -> dict:
    """
    Full hook generation. Returns {"path", "hook_text", "image_prompt"}.

    Writes a sidecar <out>.json with the metadata so run_pipeline can use the
    hook line as the video title.

    caption_override: if given (e.g. the chosen keyword TITLE), it becomes the
    on-screen caption instead of GPT's emotional hook line — so the text burned
    into the video matches the YouTube title + description keyword. GPT is still
    used for the background image prompt.
    """
    out_path = Path(out_path)
    work_dir = Path(work_dir or out_path.parent)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    copy = write_hook_copy()
    caption = clean_caption(caption_override) if caption_override else copy["hook_text"]
    print(f"  hook caption: {caption!r}")
    img_bytes = generate_image(copy["image_prompt"])

    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    base = _cover_crop(img, W, H)
    base_png = work_dir / f"{out_path.stem}_base.png"
    base.save(base_png)

    text_png = work_dir / f"{out_path.stem}_text.png"
    overlay = _text_overlay(caption)
    overlay.alpha_composite(_badge_overlay())  # "Full list in description ⌄"
    overlay.save(text_png)

    _ken_burns(base_png, text_png, out_path)

    meta = {"hook_text": caption, "image_prompt": copy["image_prompt"]}
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    # Clean intermediate frames.
    base_png.unlink(missing_ok=True)
    text_png.unlink(missing_ok=True)
    return {"path": out_path, **meta}


def _load_env_for_cli() -> None:
    """Load this folder's .env, then AssuredReferral's .env, for standalone testing."""
    for path in [HERE / ".env", HERE.parent / "assured-referral-autoposter" / ".env"]:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Generate one cozy-anime hook clip.")
    ap.add_argument("--out", type=Path, default=HERE / "work" / "gen_hook.mp4")
    args = ap.parse_args()

    _load_env_for_cli()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = generate_hook(args.out, work_dir=args.out.parent)
    print(f"✅ {result['path']}  —  {result['hook_text']!r}")
