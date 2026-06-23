"""daily.py — the hands-off cloud drip with a Telegram veto window.

Runs once each morning (GitHub Actions). It fills 4 US evening slots by, for "mix",
alternating per slot:
  • scraped — scrape a real-footage hook straight from the cloud via SCRAPE_PROXY
    (a US residential proxy; datacenter IPs are blocked by YouTube), stitch the CTA, then
  • generated — paint + publish an AI-anime Short.
A scraped slot that fails (no proxy, scrape error) falls back to generated so no slot is
wasted. 4 slots → 2 scraped + 2 generated.

Each clip is uploaded PRIVATE with publishAt = its slot (YouTube schedules it), logged
to the ledger, and previewed to Telegram with ❌/🔄 buttons. Publishing goes through
`publish.publish()` so Instagram/TikTok can be added later without touching this file.

The veto-regen calls this with `--count 1 --source generated` (build one fresh anime
Short only — no scraping).

Env: YOUTUBE_*_NINNITALES + AZURE/NINNITALES_IMAGE_* (generated) + SCRAPE_PROXY (scraped)
+ TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID.
"""

import argparse
import random
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import music_bed
import notify_telegram
import publish
import run_pipeline
import stitch_cta
from analytics import ledger

HERE = Path(__file__).parent
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
SLOT_HOURS = [12, 15, 18, 21]  # US-parent peak posting hours (ET): noon, 3, 6, 9pm
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


def _distribute(out: Path, title: str, description: str, theme: str,
                source: str, slot: str) -> bool:
    """Publish a finished clip (all platforms), log it, send the Telegram preview."""
    results = publish.publish(str(out), title, description,
                              tags=run_pipeline.TAGS, publish_at=slot)
    yt = results.get("youtube", {})
    if "error" in yt:
        print(f"  ⚠️  upload failed: {yt['error']}")
        return False
    ledger.log_upload(yt["video_id"], title, theme, yt["url"],
                      status="scheduled", publish_at=slot, source=source)
    if notify_telegram.configured():
        tg = notify_telegram.send_video_preview(
            str(out), _caption(title, theme, source, slot), veto_token=yt["video_id"])
        print("  📨 telegram preview sent" if "error" not in tg
              else f"  ⚠️  telegram: {tg['error']}")
    return True


def _make_scraped(i: int, slot: str, cta: Path, rng: random.Random,
                  cookies: str | None) -> bool:
    """Scrape a real-footage hook (cloud: via SCRAPE_PROXY), stitch + publish."""
    post = run_pipeline.choose_post(rng)
    title, description, theme = post["title"], post["description"], post["theme"]
    print(f"\n[{i+1}] scraped | {title!r} (theme={theme}) → {slot}")
    hook = run_pipeline.get_hook("scraped", run_pipeline.WORK_DIR, cookies, i,
                                 caption_override=title)
    if not hook:
        print("  ⚠️  no scraped hook available (proxy/scrape failed).")
        return False
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = run_pipeline.QUEUE_DIR / f"scraped_{stamp}_{hook['slug']}.mp4"
    try:
        stitch_cta.stitch(hook["path"], cta, out)
    except Exception as e:
        print(f"  ⚠️  stitch failed: {e}")
        return False
    music_bed.add_music(out, volume=MUSIC_VOL["scraped"])  # quiet bed under clip's own audio
    return _distribute(out, title, description, theme, "scraped", slot)


def _make_generated(i: int, slot: str, cta: Path, rng: random.Random) -> bool:
    """Build a generated (anime) Short, then publish it."""
    post = run_pipeline.choose_post(rng)
    title, description, theme = post["title"], post["description"], post["theme"]
    print(f"\n[{i+1}] generated | {title!r} (theme={theme}) → {slot}")
    hook = run_pipeline.get_hook("generated", run_pipeline.WORK_DIR, None, i,
                                 caption_override=title)
    if not hook:
        print("  ⚠️  hook generation failed — skipping this slot.")
        return False
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = run_pipeline.QUEUE_DIR / f"short_{stamp}_{hook['slug']}.mp4"
    try:
        stitch_cta.stitch(hook["path"], cta, out)
    except Exception as e:
        print(f"  ⚠️  stitch failed: {e}")
        return False
    music_bed.add_music(out, volume=MUSIC_VOL["generated"])
    return _distribute(out, title, description, theme, "generated", slot)


def run(count: int = 4, source: str = "mix") -> int:
    run_pipeline._load_env()
    run_pipeline.WORK_DIR.mkdir(exist_ok=True)
    run_pipeline.QUEUE_DIR.mkdir(exist_ok=True)
    rng = random.Random()
    ctas = sorted(run_pipeline.CTA_DIR.glob("cta*.mp4"))
    if not ctas:
        print("❌ no CTA clips found in cta/."); return 1

    cookies = str(HERE / "cookies.txt") if (HERE / "cookies.txt").exists() else None

    slots = next_slots(count)
    base = len(ledger.load())
    made = 0
    for i in range(count):
        slot = slots[i]
        cta = ctas[(base + i) % len(ctas)]
        # "mix": alternate scraped / generated per slot (even = scraped → 2+2 for count 4).
        # "generated": build only, no scraping (used by the veto-regen).
        done = False
        if source == "mix" and i % 2 == 0:
            done = _make_scraped(i, slot, cta, rng, cookies)
            if not done:
                print("  ↩️  scrape failed → filling this slot with a generated Short.")
        if not done:  # generated source, or scraped fell back
            done = _make_generated(i, slot, cta, rng)
        made += 1 if done else 0
    print(f"\nDone. {made}/{count} scheduled.")
    return 0 if made else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scrape + generate Shorts and schedule them "
                                 "with a Telegram veto window.")
    ap.add_argument("--count", type=int, default=4, help="How many slots to fill (default 4).")
    ap.add_argument("--source", choices=["mix", "generated"], default="mix",
                    help="'mix' = alternate scraped (via proxy) + generated; "
                         "'generated' = generate only.")
    args = ap.parse_args()
    raise SystemExit(run(args.count, args.source))
