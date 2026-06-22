"""daily.py — the hands-off cloud drip with a Telegram veto window.

Runs once each morning (GitHub Actions) and builds N Shorts spread across the US
evening peak slots. For each Short:

  1. pick a keyword post (run_pipeline.choose_post, weighted toward winners)
  2. get a hook — SCRAPED (real parenting footage) or GENERATED (cozy anime)
  3. stitch the captioned CTA + lay the lullaby (under any original audio)
  4. upload PRIVATE with publishAt = the next free US slot (YouTube schedules it)
  5. log to the ledger + push a Telegram preview with ❌/🔄 buttons

Default is 4/day as a 2-scraped + 2-generated MIX, so the analytics loop can measure
which content type actually wins. Do nothing and each publishes at its slot; tap ❌
to cancel or 🔄 to rebuild (telegram_poll.py). The veto-regen calls this with
--count 1 --source generated.

Env: YOUTUBE_*_NINNITALES + AZURE/NINNITALES_IMAGE_* (generated), TELEGRAM_BOT_TOKEN
+ TELEGRAM_CHAT_ID. Scraped hooks need yt-dlp (and optionally a cookies.txt).
"""

import argparse
import random
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import music_bed
import notify_telegram
import run_pipeline
import stitch_cta
import upload_youtube
from analytics import ledger

HERE = Path(__file__).parent
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
# US-parent peak posting hours (ET). 4/day spreads across these.
SLOT_HOURS = [12, 15, 18, 21]  # noon, 3pm, 6pm, 9pm
# Default content rotation for a mixed run: real footage vs AI anime, head to head.
MIX = ["scraped", "generated", "scraped", "generated"]
# Lullaby level: full when it's the only audio (generated), a quiet bed under a
# scraped clip's own sound.
MUSIC_VOL = {"generated": 0.55, "scraped": 0.30}


def next_slots(n: int, now: datetime | None = None) -> list[str]:
    """The next n upcoming SLOT_HOURS in ET, as RFC3339 UTC strings."""
    now = now or datetime.now(ET)
    out: list[datetime] = []
    day = 0
    while len(out) < n:
        for h in SLOT_HOURS:
            t = datetime.combine(now.date() + timedelta(days=day), time(h), tzinfo=ET)
            if t > now + timedelta(minutes=10):
                out.append(t)
                if len(out) == n:
                    break
        day += 1
    return [t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") for t in out]


def _caption(title: str, theme: str, source: str, slot_utc: str) -> str:
    slot_et = datetime.strptime(slot_utc, "%Y-%m-%dT%H:%M:%SZ") \
        .replace(tzinfo=UTC).astimezone(ET)
    return (
        f"🌙 <b>NinniTales — scheduled</b>\n\n"
        f"<b>Title:</b> {title}\n"
        f"<b>Source:</b> {source}   <b>Theme:</b> {theme}\n"
        f"<b>Goes live:</b> {slot_et:%a %b %d, %-I:%M %p} ET\n\n"
        f"Do nothing → it publishes automatically.\n"
        f"❌ Cancel → skip it.   🔄 → cancel &amp; build a fresh one."
    )


def _cookies() -> str | None:
    c = HERE / "cookies.txt"
    return str(c) if c.exists() else None


def _make_one(i: int, source: str, slot: str, cta: Path, rng: random.Random) -> bool:
    """Build → schedule → preview one Short. Returns True on success."""
    post = run_pipeline.choose_post(rng)
    title, description, theme = post["title"], post["description"], post["theme"]
    print(f"\n[{i+1}] {source} | {title!r} (theme={theme}) → {slot}")

    hook = run_pipeline.get_hook(source, run_pipeline.WORK_DIR, _cookies(), i,
                                 caption_override=title)
    if not hook:
        print("  ⚠️  no hook — skipping this slot.")
        return False

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = run_pipeline.QUEUE_DIR / f"short_{stamp}_{hook['slug']}.mp4"
    try:
        stitch_cta.stitch(hook["path"], cta, out)
    except Exception as e:
        print(f"  ⚠️  stitch failed: {e}")
        return False
    music_bed.add_music(out, volume=MUSIC_VOL.get(source, 0.55))

    result = upload_youtube.upload(out, title, description,
                                   tags=run_pipeline.TAGS, publish_at=slot)
    if "error" in result:
        print(f"  ⚠️  upload failed: {result['error']}")
        return False
    ledger.log_upload(result["video_id"], title, theme, result["url"],
                      status="scheduled", publish_at=slot, source=source)

    if notify_telegram.configured():
        tg = notify_telegram.send_video_preview(
            str(out), _caption(title, theme, source, slot),
            veto_token=result["video_id"])
        print("  📨 telegram preview sent" if "error" not in tg
              else f"  ⚠️  telegram: {tg['error']}")
    return True


def run(count: int = 4, source: str = "mix") -> int:
    run_pipeline._load_env()
    run_pipeline.WORK_DIR.mkdir(exist_ok=True)
    run_pipeline.QUEUE_DIR.mkdir(exist_ok=True)
    rng = random.Random()

    ctas = sorted(run_pipeline.CTA_DIR.glob("cta*.mp4"))
    if not ctas:
        print("❌ no CTA clips found in cta/."); return 1

    slots = next_slots(count)
    sources = ([MIX[i % len(MIX)] for i in range(count)] if source == "mix"
               else [source] * count)
    base = len(ledger.load())  # for stable CTA rotation across this batch
    made = 0
    for i in range(count):
        cta = ctas[(base + i) % len(ctas)]
        if _make_one(i, sources[i], slots[i], cta, rng):
            made += 1
    print(f"\nDone. {made}/{count} scheduled.")
    return 0 if made else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build + schedule N Shorts with a "
                                 "Telegram veto window.")
    ap.add_argument("--count", type=int, default=4, help="How many (default 4).")
    ap.add_argument("--source", choices=["mix", "generated", "scraped"],
                    default="mix", help="Hook source mix (default: mix).")
    args = ap.parse_args()
    raise SystemExit(run(args.count, args.source))
