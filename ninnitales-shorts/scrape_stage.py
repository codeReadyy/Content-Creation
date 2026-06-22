"""scrape_stage.py — LOCAL: scrape hooks, build Shorts, stage them for the cloud.

Runs on the Mac (residential IP) where YouTube scraping works for free — no proxy.
For each clip it: picks a keyword post, scrapes a real-footage hook, stitches the
captioned CTA + lays the lullaby, and writes the finished mp4 + a sidecar .json
(title/description/theme/source) into `pending/`. A local launchd job then commits +
pushes `pending/`, and the CLOUD daily workflow publishes them (US IP → ready for
Instagram/TikTok later).

It does NOT upload or touch the ledger — the cloud is the single publisher and ledger
writer, which avoids the local/cloud merge conflicts we hit before.

    python scrape_stage.py --count 2
"""

import argparse
import json
import random
from datetime import datetime
from pathlib import Path

import music_bed
import run_pipeline
import stitch_cta

HERE = Path(__file__).parent
PENDING = HERE / "pending"


def stage_one(i: int, rng: random.Random, cookies: str | None) -> bool:
    post = run_pipeline.choose_post(rng)
    title, description, theme = post["title"], post["description"], post["theme"]
    print(f"[{i+1}] scraped | {title!r} (theme={theme})")

    hook = run_pipeline.get_hook("scraped", run_pipeline.WORK_DIR, cookies, i,
                                 caption_override=title)
    if not hook:
        print("  ⚠️  no scraped hook available — skipping.")
        return False

    ctas = sorted(run_pipeline.CTA_DIR.glob("cta*.mp4"))
    if not ctas:
        print("  ❌ no CTA clips in cta/."); return False
    cta = ctas[i % len(ctas)]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = PENDING / f"scraped_{stamp}_{hook['slug']}.mp4"
    try:
        stitch_cta.stitch(hook["path"], cta, out)
    except Exception as e:
        print(f"  ⚠️  stitch failed: {e}")
        return False
    music_bed.add_music(out, volume=0.30)  # quiet bed under the scraped clip's own audio

    out.with_suffix(".json").write_text(json.dumps(
        {"title": title, "description": description, "tags": run_pipeline.TAGS,
         "theme": theme, "source": "scraped"}, indent=2))
    print(f"  📥 staged {out.name}")
    return True


def run(count: int, cookies: str | None) -> int:
    run_pipeline._load_env()
    run_pipeline.WORK_DIR.mkdir(exist_ok=True)
    PENDING.mkdir(exist_ok=True)
    rng = random.Random()
    made = sum(stage_one(i, rng, cookies) for i in range(count))
    print(f"\nStaged {made}/{count} scraped Shorts in pending/ (push them for the cloud).")
    return made


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scrape + build Shorts into pending/ (local).")
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--cookies", default=None,
                    help="cookies.txt for yt-dlp (defaults to ./cookies.txt if present).")
    args = ap.parse_args()
    cookies = args.cookies or (str(HERE / "cookies.txt")
                               if (HERE / "cookies.txt").exists() else None)
    raise SystemExit(0 if run(args.count, cookies) else 1)
