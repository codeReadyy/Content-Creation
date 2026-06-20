"""telegram_poll.py — act on Telegram ❌ vetoes during the scheduling window.

GitHub Actions is serverless, so we can't keep a bot running. Instead this polls
getUpdates on a short cron. For every "veto:<video_id>" button tap it:

  • deletes the scheduled YouTube video (upload_youtube.delete)
  • marks the ledger row vetoed (so analyze.py ignores it)
  • acks the tap and posts a confirmation back to the chat

Two buttons:
  "veto:<id>"  → just cancel (skip the day)
  "regen:<id>" → cancel AND signal the workflow to build a replacement. We can't
                 build a video here (the poll job is lightweight), so we emit a
                 `regenerate=true` GitHub Actions output and a conditional workflow
                 step re-runs daily.py.

Telegram's getUpdates is a cursor: once you fetch past an update_id it won't return
it again UNLESS you pass a lower offset. Across stateless runs we persist the next
offset in analytics/tg_offset.json so we never reprocess or miss a tap.
"""

import json
import os
from pathlib import Path

import notify_telegram
import run_pipeline
import upload_youtube
from analytics import ledger

OFFSET_PATH = Path(__file__).parent / "analytics" / "tg_offset.json"


def _load_offset() -> int | None:
    if OFFSET_PATH.exists():
        try:
            return int(json.loads(OFFSET_PATH.read_text()).get("offset"))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    return None


def _save_offset(update_id: int) -> None:
    OFFSET_PATH.write_text(json.dumps({"offset": update_id}, indent=2))


def _cancel(video_id: str, cb_id: str) -> bool:
    """Delete a scheduled Short + mark it vetoed. Returns True on success."""
    res = upload_youtube.delete(video_id)
    if "error" in res:
        notify_telegram.answer_callback(cb_id, "⚠️ Couldn't cancel — see logs.")
        notify_telegram.send_message(
            f"⚠️ <b>Veto failed</b> for <code>{video_id}</code>: {res['error']}")
        return False
    ledger.update(video_id, status="vetoed", finalized=True)
    return True


def _set_regenerate() -> None:
    """Signal the workflow (via GitHub Actions output) to rebuild a replacement."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write("regenerate=true\n")


def run() -> int:
    run_pipeline._load_env()
    if not notify_telegram.configured():
        print("Telegram not configured — nothing to poll.")
        return 0

    updates = notify_telegram.get_updates(offset=_load_offset())
    if not updates:
        print("No new updates.")
        return 0

    handled = regen = 0
    for u in updates:
        _save_offset(u["update_id"] + 1)  # advance cursor even for ignored updates
        cb = u.get("callback_query")
        if not cb:
            continue
        action, _, video_id = cb.get("data", "").partition(":")
        if action not in ("veto", "regen") or not video_id:
            continue
        print(f"  {action} tap → {video_id}")
        if not _cancel(video_id, cb["id"]):
            continue
        handled += 1
        if action == "regen":
            regen += 1
            notify_telegram.answer_callback(cb["id"], "Making another… 🔄")
            notify_telegram.send_message(
                f"🔄 <b>Cancelled <code>{video_id}</code> — building a fresh one…</b>")
        else:
            notify_telegram.answer_callback(cb["id"], "Cancelled ✅")
            notify_telegram.send_message(
                f"❌ <b>Cancelled.</b> <code>{video_id}</code> won't go live. "
                "No post today.")
    if regen:
        _set_regenerate()  # workflow's conditional step re-runs daily.py
    print(f"Processed {handled} cancel(s), {regen} regenerate(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
