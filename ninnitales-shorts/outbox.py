"""outbox.py — stash a built pin for MANUAL posting (no API publish).

While the Pinterest app is on Trial access it can't create pins in production, so this
lets the full pipeline still run (research → ghostwriter copy → gpt-image-2 image → board
+ link) and drop each pin into an outbox folder you post by hand in ~30s:

  outbox/<YYYY-MM-DD>/<slug>.png        the pin image
  outbox/<YYYY-MM-DD>/<slug>.txt        copy-paste fields (title, description, board, link)
  outbox/index.csv                      one row per stashed pin (a running log)

To post: open Pinterest → Create Pin → upload the .png → copy the title/description/link
from the .txt → pick the board. When Standard access lands, switch back to
`--now N` (real API publish) and this becomes unnecessary.

Not Pinterest-specific in principle (it stashes any Asset), but the fields it records
(board, link) are what a pin needs.
"""

from __future__ import annotations

import csv
import re
import shutil
from datetime import datetime
from pathlib import Path

from core.models import Account, Asset, PostCopy

HERE = Path(__file__).parent
OUTBOX = HERE / "outbox"
INDEX = OUTBOX / "index.csv"
_FIELDS = ["date", "account", "board", "title", "link", "hashtags", "image", "description"]


def _slug(text: str, n: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "pin").lower()).strip("-")
    return (s[:n] or "pin").rstrip("-")


def stash(asset: Asset, copy: PostCopy, account: Account) -> Path:
    """Write the pin's image + a copy-paste sidecar, and append to index.csv.

    Returns the image path written."""
    day = datetime.now().strftime("%Y-%m-%d")
    stamp = datetime.now().strftime("%H%M%S")
    dest_dir = OUTBOX / day
    dest_dir.mkdir(parents=True, exist_ok=True)

    board = asset.meta.get("board", "")
    link = asset.meta.get("link", "")
    hashtags = " ".join(copy.hashtags or asset.meta.get("hashtags", []))
    base = f"{stamp}_{_slug(copy.title)}"
    img_path = dest_dir / f"{base}{asset.path.suffix}"
    shutil.copy(asset.path, img_path)

    (dest_dir / f"{base}.txt").write_text(
        f"TITLE:\n{copy.title}\n\n"
        f"DESCRIPTION:\n{copy.caption}\n\n"
        f"BOARD:     {board}\n"
        f"LINK:      {link}\n"
        f"HASHTAGS:  {hashtags}\n"
        f"IMAGE:     {img_path.name}\n"
    )

    new = not INDEX.exists()
    with INDEX.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        if new:
            w.writeheader()
        w.writerow({
            "date": day, "account": account.id, "board": board,
            "title": copy.title, "link": link, "hashtags": hashtags,
            "image": str(img_path.relative_to(OUTBOX)), "description": copy.caption,
        })
    return img_path
