"""daily.py — the hands-off cloud drip with a Telegram veto window.

Runs once each morning (GitHub Actions), ~2h before the first slot. It fills 3 ET
slots (Morning Rush 8:00am, Midday Break 12:30pm, Prime Time 7:00pm) by, for "mix",
alternating per slot:
  • scraped — scrape a real-footage hook straight from the cloud via SCRAPE_PROXY
    (a US residential proxy; datacenter IPs are blocked by YouTube), stitch the CTA, then
  • generated — paint + publish an AI-anime Short.
A scraped slot that fails (no proxy, scrape error) falls back to generated so no slot is
wasted. 3 slots → 2 scraped + 1 generated.

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

import ghostwriter
import music_bed
import notify_telegram
import publish
import run_pipeline
import stitch_cta
import token_doctor
from analytics import ledger

HERE = Path(__file__).parent
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
# US-parent peak windows (ET), (hour, minute): Morning Rush 8:00, Midday Break 12:30,
# Prime Time 7:00pm. The build runs ~2h before the first slot, so every Short gets at
# least a 2-hour Telegram veto window before it goes live.
SLOT_TIMES = [(8, 0), (12, 30), (19, 0)]
# Lullaby level: full when it's the only audio (generated), a quiet bed under a
# scraped clip's own sound.
MUSIC_VOL = {"generated": 0.55, "scraped": 0.30}


def next_slots(n: int, now: datetime | None = None) -> list[str]:
    """The next n upcoming SLOT_TIMES in ET, as RFC3339 UTC strings."""
    now = now or datetime.now(ET)
    out: list[datetime] = []
    day = 0
    while len(out) < n:
        for h, m in SLOT_TIMES:
            t = datetime.combine(now.date() + timedelta(days=day), time(h, m), tzinfo=ET)
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


def _health_status(health: dict) -> str:
    """A one-glance token snapshot, sent every run so the picture is always clear."""
    if not health["alive"]:
        return (f"❌ <b>YouTube token DEAD</b>\n"
                f"Reason: <code>{health['error']}</code>\n"
                f"From: {health['source']}\n"
                f"Fix: <code>python get_youtube_token.py</code> → update .env AND the "
                f"GitHub secret.")
    analytics = "✅" if health.get("analytics_ok") else "⚠️ no"
    chan = health.get("channel_title") or "(unknown)"
    return (f"✅ <b>YouTube token healthy</b>\n"
            f"Channel: {chan}\n"
            f"Analytics: {analytics}   Scopes: force-ssl + analytics\n"
            f"From: {health['source']}")


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
                  cookies: str | None, avoid: list[str]) -> bool:
    """Scrape a real-footage hook (cloud: via SCRAPE_PROXY), stitch + publish.

    Scraped footage can't be read, so it gets a ROTATING brand/social-proof title
    (dedup'd within the week) + ONE fixed brand description — never a content-specific
    listicle that might not match the clip.
    """
    post = run_pipeline.choose_scraped_post(rng, avoid_titles=avoid)
    title, description, theme = post["title"], post["description"], post["theme"]
    avoid.append(title)
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


def _make_generated(i: int, slot: str, cta: Path, rng: random.Random,
                    avoid: list[str]) -> bool:
    """Build a generated (anime) Short, then publish it.

    The ghostwriter LLM writes a FRESH title + description from today's keyword
    themes, the winning-theme weights, the last Shorts' real numbers, and the
    titles to avoid — so generated captions never repeat. If it can't (no Azure
    creds, content filter, etc.) we fall back to the dedup'd templates.
    """
    post = (ghostwriter.write_post(rng, avoid_titles=avoid)
            or run_pipeline.choose_post(rng, avoid_titles=avoid))
    title, description, theme = post["title"], post["description"], post["theme"]
    avoid.append(title)
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


def run(count: int = 3, source: str = "mix") -> int:
    run_pipeline._load_env()
    run_pipeline.WORK_DIR.mkdir(exist_ok=True)
    run_pipeline.QUEUE_DIR.mkdir(exist_ok=True)

    # Pre-flight: check the token EVERY run and report it to Telegram so the picture
    # is always clear — a green tick on healthy days, the exact reason on a dead one.
    # A dead token aborts here so we never waste upload slots on invisible 401s.
    health = token_doctor.check()
    tg = notify_telegram.configured()
    if tg:
        notify_telegram.send_message(
            f"🌙 <b>NinniTales daily run</b>\n\n{_health_status(health)}")
    if not health["alive"]:
        print(f"❌ token dead ({health['error']}) — aborting before wasting slots.")
        return 1

    rng = random.Random()
    ctas = sorted(run_pipeline.CTA_DIR.glob("cta*.mp4"))
    if not ctas:
        print("❌ no CTA clips found in cta/."); return 1

    cookies = str(HERE / "cookies.txt") if (HERE / "cookies.txt").exists() else None

    slots = next_slots(count)
    base = len(ledger.load())
    # Titles used in the last week + anything we schedule in THIS run — so no two
    # Shorts (across both sources) ever go out with the same caption.
    avoid = run_pipeline.recent_titles()
    made = 0
    for i in range(count):
        slot = slots[i]
        cta = ctas[(base + i) % len(ctas)]
        # "mix": alternate scraped / generated per slot (even = scraped → 2+2 for count 4).
        # "generated": build only, no scraping (used by the veto-regen).
        done = False
        if source == "mix" and i % 2 == 0:
            done = _make_scraped(i, slot, cta, rng, cookies, avoid)
            if not done:
                print("  ↩️  scrape failed → filling this slot with a generated Short.")
        if not done:  # generated source, or scraped fell back
            done = _make_generated(i, slot, cta, rng, avoid)
        made += 1 if done else 0
    print(f"\nDone. {made}/{count} scheduled.")
    if tg:
        icon = "✅" if made == count else ("⚠️" if made else "❌")
        notify_telegram.send_message(
            f"{icon} <b>NinniTales run done</b> — scheduled {made}/{count} Shorts for "
            f"today's ET slots. Previews above; do nothing to publish, ❌ to veto.")
    return 0 if made else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scrape + generate Shorts and schedule them "
                                 "with a Telegram veto window.")
    ap.add_argument("--count", type=int, default=3, help="How many slots to fill (default 3).")
    ap.add_argument("--source", choices=["mix", "generated"], default="mix",
                    help="'mix' = alternate scraped (via proxy) + generated; "
                         "'generated' = generate only.")
    args = ap.parse_args()
    raise SystemExit(run(args.count, args.source))
