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
import random
from datetime import datetime
from pathlib import Path

import stitch_cta
import upload_youtube
from analytics import ledger

HERE = Path(__file__).parent
CTA_DIR = HERE / "cta"
WORK_DIR = HERE / "work"
QUEUE_DIR = HERE / "queue"

# Waitlist for now (pre-launch). Swap to the app-store links at launch.
WAITLIST_URL = "https://ninnitales.com"

# ── SEARCH-FIRST TITLES ──────────────────────────────────────────────────────
# Titles lead with a phrase parents actually type into YouTube search (sourced
# from YouTube autocomplete, US), because Shorts surface heavily in search and a
# keyword title ("best way to put kids to sleep") out-pulls a clever one
# ("this changed everything") by ~100x in this niche. Keep the keyword in the
# FIRST ~40 chars (mobile truncates). Each post carries a `theme` (keyword bucket)
# so analyze.py can attribute views back to it and run_pipeline can double down on
# the winners. The on-screen hook is independent of this metadata.
def _desc(title: str, steps: list[str], tags: str) -> str:
    """Build a VALUE-LIST description that delivers on the title's promise.

    The first line (all YouTube shows before "...more") echoes the on-screen title,
    so a viewer who saw "5 ways..." taps to get the actual 5 ways. The list is real,
    usable advice; ONE item (the 2nd or 3rd) is the NinniTales method described in
    plain human words — no hard sell. A single soft link sits at the very bottom.
    """
    body = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
    return (
        f"{title} 👇\n\n"
        f"{body}\n\n"
        "Save this for tonight. 🌙\n\n"
        f"(The record-your-voice idea above is what we made → {WAITLIST_URL})\n\n"
        f"{tags}"
    )


# Each post is a LISTICLE: the title is a "N ways/steps" hook (also burned on-screen),
# and the description delivers that real list. The NinniTales method is woven in as
# item 2 or 3 in human words ("play a story in your own recorded voice"), never a pitch.
POSTS = [
    {"theme": "sleep_fast",
     "title": "5 ways to get your toddler to sleep faster",
     "description": _desc(
         "5 ways to get your toddler to sleep faster",
         ["Start the wind-down an hour early — dim the lights so their body clock catches on.",
          "Play a story in YOUR voice — record yourself reading their favorite book once, "
          "then play it back at lights-out. A familiar voice settles little ones faster than "
          "any screen, even on the nights you're not in the room (this is the whole idea "
          "behind NinniTales).",
          "Keep the room cool and dark — around 68°F is the sleep sweet spot.",
          "Same three steps every night — bath, book, bed — so bedtime feels predictable.",
          "No screens for the last 30 minutes — blue light keeps them wired."],
         "#toddlersleep #howtogettoddlertosleep #bedtime #momlife #parentinghacks")},
    {"theme": "wont_sleep",
     "title": "4 things to try when your toddler won't sleep",
     "description": _desc(
         "4 things to try when your toddler won't sleep",
         ["Check the basics first — too hot, too cold, hungry, or overtired all backfire.",
          "Lower your voice and slow down — kids mirror your energy, so calm is contagious.",
          "Play a bedtime story in your own recorded voice — hearing mom or dad on repeat "
          "reassures them and ends the 'stay with me' battle, even when you've left the room "
          "(an app like NinniTales makes this easy).",
          "Keep night responses boring and brief so bedtime stays bedtime."],
         "#toddlerwontsleep #bedtimebattle #toddlermom #parenting #sleeptips")},
    {"theme": "bedtime_routine",
     "title": "5 steps to a bedtime routine that actually works",
     "description": _desc(
         "5 steps to a bedtime routine that actually works",
         ["Set a fixed bedtime and protect it — consistency is what makes routines stick.",
          "Warm bath to signal the day is ending.",
          "One story, same spot — and on the nights you travel or work late, play it in your "
          "own recorded voice so bedtime still sounds like home (that's why we built NinniTales).",
          "Dim lights and quiet voices for the last stretch.",
          "Same goodnight phrase every night — little rituals cue sleep."],
         "#bedtimeroutine #toddlerbedtime #momlife #parentinghacks #toddlermom")},
    {"theme": "through_night",
     "title": "5 ways to help your baby sleep through the night",
     "description": _desc(
         "5 ways to help your baby sleep through the night",
         ["Full feed before bed so hunger doesn't wake them.",
          "Consistent wind-down — same order, same time, every night.",
          "Give them a familiar sound to self-settle to — soft white noise, or your own "
          "voice reading a story on a gentle loop (apps like NinniTales let you record it once).",
          "Put them down drowsy but awake so they learn to drift off on their own.",
          "Keep night wakings boring — low light, low voice, minimal fuss."],
         "#babysleep #sleepthroughthenight #newmom #babysleeptips #momlife")},
    {"theme": "make_sleep",
     "title": "5 tricks to make kids fall asleep faster",
     "description": _desc(
         "5 tricks to make kids fall asleep faster",
         ["Cool, dark room — fewer cues to stay awake.",
          "A predictable routine so their brain knows what's coming.",
          "Let them hear a familiar voice — record yourself reading a story and play it at "
          "lights-out; kids settle to mom or dad faster than to a screen (NinniTales is built "
          "for exactly this).",
          "Cut sugar and rough play in the last hour.",
          "Keep goodnights short and sweet — long ones invite negotiation."],
         "#kidssleep #bedtimehack #parentinghacks #momhacks #toddlersleep")},
    {"theme": "calm_before_bed",
     "title": "4 ways to calm an overtired toddler before bed",
     "description": _desc(
         "4 ways to calm an overtired toddler before bed",
         ["Slow everything down — your calm sets their calm.",
          "Dim the lights and cut the noise 30 minutes out.",
          "Play a soft bedtime story in your own voice — a familiar voice lowers the meltdown "
          "faster than rocking or a screen (this is what NinniTales does).",
          "Offer one small choice — which pajamas, which story — so they feel in control."],
         "#calmtoddler #overtired #bedtimebattle #toddlermom #parentinghacks")},
    {"theme": "bedtime_stories",
     "title": "5 bedtime stories that put kids to sleep",
     "description": _desc(
         "5 bedtime stories that put kids to sleep",
         ["Slow, repetitive tales — the boring-on-purpose kind that ease them down.",
          "Old favorites they know by heart — familiarity is soothing.",
          "The same story in YOUR voice — record it once and play it any night, so they hear "
          "you even when you're away (that's the idea behind NinniTales).",
          "Gentle 'goodnight' books that name the winding-down actions.",
          "A made-up story starring them — personal and calming."],
         "#bedtimestories #storytime #kidsbedtime #toddlermom #parenting")},
]
TAGS = ["bedtime stories", "how to get toddler to sleep", "toddler won't sleep",
        "toddler sleep", "bedtime routine", "how to make kids sleep", "kids sleep",
        "toddler bedtime", "bedtime stories for kids", "ninnitales"]
# Fallbacks for approve.py when a queued clip has no sidecar metadata.
DESCRIPTION = POSTS[0]["description"]

# analyze.py writes per-theme weights here after measuring 24h performance.
WINNERS_PATH = HERE / "analytics" / "winners.json"
# Share of picks reserved for EXPLORING themes regardless of past results, so a
# new keyword still gets a fair shot and we don't over-fit to early noise.
EXPLORE_RATE = 0.20


def _theme_weights() -> dict[str, float]:
    """Load per-theme weights produced by analyze.py (empty until it has run)."""
    if not WINNERS_PATH.exists():
        return {}
    try:
        data = json.loads(WINNERS_PATH.read_text())
        return {k: float(v) for k, v in data.get("theme_weights", {}).items()}
    except (json.JSONDecodeError, ValueError, AttributeError):
        return {}


def choose_post(rng: random.Random) -> dict:
    """Pick a post, biased toward themes that earned views (explore/exploit).

    With probability EXPLORE_RATE (or before analyze.py has any data) pick
    uniformly so every theme keeps getting tested; otherwise pick a theme with
    probability proportional to its measured weight, then a random title in it.
    """
    weights = _theme_weights()
    if not weights or rng.random() < EXPLORE_RATE:
        return rng.choice(POSTS)
    themes = sorted({p["theme"] for p in POSTS})
    scored = [max(weights.get(t, 0.0), 0.0) for t in themes]
    if sum(scored) <= 0:
        return rng.choice(POSTS)
    theme = rng.choices(themes, weights=scored, k=1)[0]
    return rng.choice([p for p in POSTS if p["theme"] == theme])


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


def get_hook(source: str, work_dir: Path, cookies: str | None, idx: int,
             caption_override: str | None = None) -> dict | None:
    """
    Return a hook for one video: {"path", "slug", "title"}.

    source: "generated" | "scraped" | "mix" (mix alternates, starting generated).
    caption_override: the keyword title to burn on-screen (generated hooks only),
    so the on-screen text matches the YouTube title + description keyword.
    """
    if source == "mix":
        source = "generated" if idx % 2 == 0 else "scraped"

    if source == "generated":
        import generate_hook  # imported lazily so scraped-only runs need no openai/PIL
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = work_dir / f"genhook_{stamp}.mp4"
        try:
            res = generate_hook.generate_hook(out, work_dir=work_dir,
                                              caption_override=caption_override)
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
    rng = random.Random()  # performance-weighted title selection (see choose_post)
    made = 0

    for i in range(count):
        print(f"\n=== video {i + 1}/{count} (source={source}) ===")
        # Pick the keyword post FIRST so its title can drive the on-screen caption.
        post = choose_post(rng)  # keyword title, weighted toward proven themes
        title, description, theme = post["title"], post["description"], post["theme"]
        print(f"  title: {title!r}  (theme={theme})")

        hook = get_hook(source, WORK_DIR, cookies, i, caption_override=title)
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

        if stitch_only:
            # Stash the metadata next to the clip so approve.py can publish it later
            # with the right title + theme without re-deriving anything.
            out.with_suffix(".json").write_text(json.dumps(
                {"title": title, "description": description, "tags": TAGS,
                 "theme": theme}, indent=2))
            print(f"  📦 queued (no upload): {out}")
            made += 1
            continue

        result = upload_youtube.upload(out, title, description, tags=TAGS)
        if "error" in result:
            print(f"  ⚠️  upload failed: {result['error']}")
            continue
        ledger.log_upload(result["video_id"], title, theme, result["url"])
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
