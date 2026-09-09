"""characters.py — the recurring photoreal cast for realistic carousels.

Locks a consistent "NinniTales mom" and "dad" (assets/characters/{mom,dad}.png, approved
once) and, via gpt-image-2's image-EDIT endpoint, drops that SAME person into a fresh
messy-home scene for each post — so the family stays consistent across every carousel
with no extra tool. The child is always IMPLIED (plush toy, tiny shoes, empty crib), never
depicted: image models refuse realistic minors and it's a brand/legal minefield.

Falls back to the warm gradient (formats.pin._gradient) if the image API is missing/slow,
so a build never blocks. Edits run at ~2-4 min each, so callers use this for the ONE cover
slide only (value slides stay on the fast gradient renderer).
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from pathlib import Path

import requests
import llm
from PIL import Image

HERE = Path(__file__).parent
CHAR_DIR = HERE / "assets" / "characters"
LOCKED = {"mom": CHAR_DIR / "mom.png", "dad": CHAR_DIR / "dad.png"}

REAL_STYLE = ("Photorealistic candid documentary photograph, natural soft window and lamp "
              "light, shot on 35mm film, authentic and imperfect, warm cozy color grade, "
              "real skin with no glamour retouching")

# Fallback cover scenes (used when the LLM doesn't supply one) — always a tired parent in
# a lived-in messy home, child implied.
FALLBACK_SCENES = [
    "sitting on the edge of an unmade bed in a messy bedroom at night, exhausted but "
    "tender, laundry and toys around, a plush bunny and tiny shoes on the floor",
    "leaning in a doorway holding a coffee mug, looking into a messy nursery with an "
    "empty crib and scattered blocks, dark circles, gentle tired smile",
    "kneeling to tidy scattered toys and books on a rug in a cozy lamplit living room, "
    "a folded blanket on the couch, worn out but caring",
]


def available() -> bool:
    return all(p.exists() for p in LOCKED.values())


def _creds() -> tuple[str, str]:
    """(base_url, key) for the image model — provider config lives in llm.py."""
    return llm.image_creds()


def scene(character: str, scene_prompt: str, w: int, h: int,
          quality: str = "medium", timeout: int = 600) -> Image.Image:
    """Place the locked `character` (mom|dad) into `scene_prompt`, cover-cropped to w x h.

    Gradient fallback on any failure (missing ref, no creds, timeout, safety filter)."""
    from formats import pin as pin_fmt
    ref = LOCKED.get(character)
    if not ref or not ref.exists():
        return pin_fmt._gradient(w, h)
    try:
        base, key = _creds()
        prompt = (f"{REAL_STYLE}. The SAME person (identical face, hair, build) as the "
                  f"reference image, {scene_prompt}. NO child visible in the frame. "
                  "Vertical composition.")
        with open(ref, "rb") as f:
            r = requests.post(f"{base}/images/edits",
                              headers={"Authorization": f"Bearer {key}"},
                              data={"model": llm.image_model(), "prompt": prompt,
                                    "size": "1024x1536"},
                              files={"image": (ref.name, f, "image/png")}, timeout=timeout)
        r.raise_for_status()
        raw = base64.b64decode(r.json()["data"][0]["b64_json"])
        img = Image.open(BytesIO(raw)).convert("RGB")
        import generate_hook
        return generate_hook._cover_crop(img, w, h)
    except Exception as e:
        print(f"  ⚠️  realistic scene failed ({e}) — gradient fallback.")
        return pin_fmt._gradient(w, h)
