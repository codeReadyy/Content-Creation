"""
run_pipeline.py — the NinniTales daily loop: get hook → stitch CTA → upload.

Hooks come from one of two sources (you can mix them):
  • generated — original cozy-anime hook (generate_hook.py). Safe, on-brand, free.
  • scraped   — first ~3s of a fresh Short from your channel list (scrape_hooks.py).

For each video:
  1. get a hook clip from the chosen source
  2. stitch a rotating CTA onto the end (stitch_cta.stitch)
  3. upload to the NinniTales channel (upload_youtube.upload)

Runs locally or from a GitHub Actions cron. Keep --count small (<=5/day) to stay
under the channel's daily upload limit and the API quota.

Examples:
    python run_pipeline.py --count 1 --source generated
    python run_pipeline.py --count 2 --source mix
    python run_pipeline.py --count 1 --source scraped --cookies cookies.txt
    python run_pipeline.py --count 1 --stitch-only        # build, don't upload
"""

import argparse
import itertools
import json
import os
from datetime import datetime
from pathlib import Path

import stitch_cta
import upload_youtube

HERE = Path(__file__).parent
CTA_DIR = HERE / "cta"
WORK_DIR = HERE / "work"
QUEUE_DIR = HERE / "queue"

# Fallback titles when a hook has no generated line (i.e. scraped hooks).
# Waitlist for now (pre-launch). Swap to the app-store links at launch.
WAITLIST_URL = "https://ninnitales.com"

# Title + description rotate through these sets (round-robin), independent of the
# on-screen hook. Rotating avoids YouTube's duplicate-metadata spam throttling.
# At launch: change the CTA line + WAITLIST_URL to the store link.
POSTS = [
    {
        "title": "She falls asleep to my voice — even when I'm not home 🌙",
        "description": (
            "Work trips. Late shifts. Bedtime shouldn't have to wait.\n\n"
            "NinniTales reads bedtime stories in YOUR real voice — record once, "
            "play any night, anywhere.\n\n"
            f"✨ Join the early-access waitlist → {WAITLIST_URL}\n\n"
            "#bedtimestories #momlife #dadlife #parentinghacks #toddlermom #bedtime #storytime"
        ),
    },
    {
        "title": "Record your voice ONCE → bedtime stories in your voice forever",
        "description": (
            "90 seconds of your voice today = endless bedtime stories in YOUR voice, "
            "every night — even when you can't be there.\n\n"
            f"✨ Be first to try it → {WAITLIST_URL}\n\n"
            "#parenting #bedtime #newparents #storytime #kidsbedtime #momlife"
        ),
    },
    {
        "title": 'My toddler won\'t sleep without "one more story" 🥹 (in my voice)',
        "description": (
            "The magic isn't the story — it's hearing Mom or Dad tell it.\n\n"
            "NinniTales narrates bedtime stories in your own voice, so goodnight "
            "always sounds like home.\n\n"
            f"✨ Join the waitlist → {WAITLIST_URL}\n\n"
            "#toddlermom #momlife #bedtimestories #parentinghacks #dadlife"
        ),
    },
    {
        "title": "How my kid hears my voice at bedtime — even miles away",
        "description": (
            "The bedtime hack every busy & traveling parent needs: record your voice "
            "once, and NinniTales reads stories in YOUR voice anywhere, any night.\n\n"
            f"✨ Get early access → {WAITLIST_URL}\n\n"
            "#parenting #dadlife #bedtime #momhacks #storytime #toddlermom"
        ),
    },
]
TAGS = ["bedtime stories", "parenting", "toddler", "kids", "bedtime",
        "mom", "dad", "ninnitales", "kids audio", "storytime"]
# Fallbacks for approve.py when a queued clip has no sidecar metadata.
DESCRIPTION = POSTS[0]["description"]


def _load_env() -> None:
    """Load env from ninnitales-shorts/.env, then AssuredReferral's .env as fallback.

    Local values win; the AssuredReferral .env supplies the shared Azure + YouTube
    credentials so we don't duplicate them. No-op if files are absent.
    """
    for path in [HERE / ".env", HERE.parent / "assured-referral-autoposter" / ".env"]:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def cta_cycle():
    """Round-robin over the available CTA clips."""
    ctas = sorted(CTA_DIR.glob("cta*.mp4"))
    if not ctas:
        raise SystemExit(f"❌ No CTA clips in {CTA_DIR}")
    return itertools.cycle(ctas)


def get_hook(source: str, work_dir: Path, cookies: str | None, idx: int) -> dict | None:
    """
    Return a hook for one video: {"path", "slug", "title"}.

    source: "generated" | "scraped" | "mix" (mix alternates, starting generated).
    """
    if source == "mix":
        source = "generated" if idx % 2 == 0 else "scraped"

    if source == "generated":
        import generate_hook  # imported lazily so scraped-only runs need no openai/PIL
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = work_dir / f"genhook_{stamp}.mp4"
        try:
            res = generate_hook.generate_hook(out, work_dir=work_dir)
        except Exception as e:
            print(f"  ⚠️  hook generation failed: {e}")
            return None
        return {"path": res["path"], "slug": "gen", "title": res["hook_text"]}

    # scraped
    import scrape_hooks
    hook = scrape_hooks.next_hook(work_dir, cookies)
    if not hook:
        return None
    return {"path": hook["path"], "slug": hook["video_id"], "title": None}


def run(count: int, source: str, cookies: str | None, stitch_only: bool) -> int:
    _load_env()
    WORK_DIR.mkdir(exist_ok=True)
    QUEUE_DIR.mkdir(exist_ok=True)
    ctas = cta_cycle()
    posts = itertools.cycle(POSTS)  # title+description rotation, independent of the hook
    made = 0

    for i in range(count):
        print(f"\n=== video {i + 1}/{count} (source={source}) ===")
        hook = get_hook(source, WORK_DIR, cookies, i)
        if not hook:
            print("no hook available — skipping.")
            continue

        cta = next(ctas)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = QUEUE_DIR / f"short_{stamp}_{hook['slug']}.mp4"
        print(f"stitching {Path(hook['path']).name} + {cta.name} -> {out.name}")
        try:
            stitch_cta.stitch(hook["path"], cta, out)
        except Exception as e:
            print(f"  ⚠️  stitch failed, skipping: {e}")
            continue

        post = next(posts)  # rotating title + description (not the on-screen hook)
        title, description = post["title"], post["description"]
        if stitch_only:
            # Stash the metadata next to the clip so approve.py can publish it later
            # with the right title without re-deriving anything.
            out.with_suffix(".json").write_text(json.dumps(
                {"title": title, "description": description, "tags": TAGS}, indent=2))
            print(f"  📦 queued (no upload): {out}")
            made += 1
            continue

        result = upload_youtube.upload(out, title, description, tags=TAGS)
        if "error" in result:
            print(f"  ⚠️  upload failed: {result['error']}")
            continue
        made += 1

    print(f"\nDone. {made}/{count} video(s) "
          f"{'built' if stitch_only else 'published'}.")
    return made


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run the NinniTales Shorts pipeline.")
    ap.add_argument("--count", type=int, default=1, help="How many to make (<=5/day).")
    ap.add_argument("--source", choices=["generated", "scraped", "mix"],
                    default="generated", help="Where hooks come from (default: generated).")
    ap.add_argument("--cookies", default=None, help="cookies.txt for yt-dlp (scraped only).")
    ap.add_argument("--stitch-only", action="store_true",
                    help="Build videos into queue/ but do not upload.")
    args = ap.parse_args()
    run(args.count, args.source, args.cookies, args.stitch_only)
