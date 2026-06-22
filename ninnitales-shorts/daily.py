"""daily.py — the hands-off cloud drip with a Telegram veto window.

Runs once each morning (GitHub Actions). For one Short:

  1. build a generated cozy-anime hook + stitch a CTA   (run_pipeline helpers)
  2. pick a SEARCH keyword title weighted toward winners (run_pipeline.choose_post)
  3. upload PRIVATE with publishAt = the next 7pm ET slot (YouTube schedules it)
  4. log it to the ledger as "scheduled"
  5. push the clip to Telegram with a ❌ Cancel button

Do nothing and YouTube publishes it at 7pm ET. Tap ❌ within the window and
telegram_poll.py deletes it before it ever goes live. The analyze cron measures it
24h after the scheduled time and feeds winners.json — closing the loop.

Env: the YOUTUBE_*_NINNITALES + AZURE/NINNITALES_IMAGE_* secrets (as today), plus
TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (reused from AssuredReferral).
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
SLOT_HOUR = 19  # 7pm ET — the US-parent evening / live-bedtime peak


def next_slot_utc(now: datetime | None = None) -> str:
    """RFC3339 UTC for the next SLOT_HOUR in ET (today if still ahead, else tomorrow)."""
    now = now or datetime.now(ET)
    target = datetime.combine(now.date(), time(SLOT_HOUR), tzinfo=ET)
    if target <= now + timedelta(minutes=10):  # too close / already past → tomorrow
        target += timedelta(days=1)
    return target.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def _caption(title: str, theme: str, slot_utc: str) -> str:
    slot_et = datetime.strptime(slot_utc, "%Y-%m-%dT%H:%M:%SZ") \
        .replace(tzinfo=ZoneInfo("UTC")).astimezone(ET)
    return (
        f"🌙 <b>NinniTales — scheduled</b>\n\n"
        f"<b>Title:</b> {title}\n"
        f"<b>Keyword theme:</b> {theme}\n"
        f"<b>Goes live:</b> {slot_et:%a %b %d, %-I:%M %p} ET\n\n"
        f"Do nothing → it publishes automatically.\n"
        f"❌ Cancel → skip today.   🔄 → cancel &amp; build a fresh one."
    )


def run() -> int:
    run_pipeline._load_env()
    run_pipeline.WORK_DIR.mkdir(exist_ok=True)
    run_pipeline.QUEUE_DIR.mkdir(exist_ok=True)
    rng = random.Random()

    # Pick the keyword post first so its title drives the on-screen caption too.
    post = run_pipeline.choose_post(rng)
    title, description, theme = post["title"], post["description"], post["theme"]
    slot = next_slot_utc()
    print(f"title: {title!r}  (theme={theme})  → schedule {slot}")

    hook = run_pipeline.get_hook("generated", run_pipeline.WORK_DIR, None, 0,
                                 caption_override=title)
    if not hook:
        print("❌ hook generation failed — nothing to post today.")
        return 1

    # Rotate CTAs across DAYS. daily.py is a fresh process each run, so a new
    # itertools.cycle would always hand back cta1 — instead index by how many we've
    # logged so far so cta1 → cta2 → cta3 → cta1 … evenly over time.
    ctas = sorted(run_pipeline.CTA_DIR.glob("cta*.mp4"))
    if not ctas:
        print("❌ no CTA clips found in cta/."); return 1
    cta = ctas[len(ledger.load()) % len(ctas)]
    print(f"  cta: {cta.name}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = run_pipeline.QUEUE_DIR / f"short_{stamp}_{hook['slug']}.mp4"
    stitch_cta.stitch(hook["path"], cta, out)
    music_bed.add_music(out)  # one continuous lullaby across hook + CTA

    result = upload_youtube.upload(out, title, description,
                                   tags=run_pipeline.TAGS, publish_at=slot)
    if "error" in result:
        print(f"❌ upload failed: {result['error']}")
        return 1

    ledger.log_upload(result["video_id"], title, theme, result["url"],
                      status="scheduled", publish_at=slot)

    if notify_telegram.configured():
        tg = notify_telegram.send_video_preview(
            str(out), _caption(title, theme, slot), veto_token=result["video_id"])
        print("  📨 telegram preview sent" if "error" not in tg
              else f"  ⚠️  telegram: {tg['error']}")
    else:
        print("  ⚠️  Telegram not configured — no veto preview "
              "(set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID).")
    return 0


if __name__ == "__main__":
    argparse.ArgumentParser(description="Build + schedule one Short with a "
                            "Telegram veto window.").parse_args()
    raise SystemExit(run())
