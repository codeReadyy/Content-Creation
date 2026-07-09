"""engage.py — reply to keyword comments on Instagram carousels with bonus content.

The comment_keyword engagement CTA ("Comment SLEEP and we'll reply with the full
checklist") only works if something actually replies. This is that something — the
self-hosted stand-in for the ManyChat setups big accounts use. Runs on a 2-hourly
cron (.github/workflows/ninnitales-engage.yml):

  • finds ledger rows from the last REPLY_WINDOW_DAYS where engagement_cta ==
    "comment_keyword" (the keyword + bonus_content were stored at post time),
  • pulls each post's comments from the IG Graph API,
  • replies to keyword-matching comments (case-insensitive) with the bonus content
    + a warm thank-you line, tracking replied comment ids in the ledger row so it's
    idempotent across runs,
  • caps replies per run (rate-limit / anti-spam) and no-ops silently when idle.

If the token turns out to lack the comments permission, this records
{"comments_scope_ok": false} in analytics/engage_state.json — formats/carousel.py
reads that and STOPS offering the comment_keyword CTA, so no post ever promises a
reply we can't deliver — and raises a Telegram alert once.

Usage:
    python engage.py            # poll + reply
    python engage.py --dry-run  # show what would be replied, post nothing
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from analytics import ledger

try:
    import run_pipeline
    run_pipeline._load_env()
except Exception:                                   # engage runs fine on bare env vars
    pass

try:
    import notify_telegram
except Exception:                                   # pragma: no cover
    notify_telegram = None

IG_GRAPH = "https://graph.instagram.com/v21.0"
STATE_PATH = Path(__file__).parent / "analytics" / "engage_state.json"
REPLY_WINDOW_DAYS = 3
MAX_REPLIES_PER_RUN = 20
THANKS = "You're doing great. 💛"


def _token(account_id: str | None) -> str | None:
    suffix = "NINNITALES"
    try:
        from core import config
        if account_id:
            suffix = config.get_account(account_id).creds_env
    except Exception:
        pass
    return (os.environ.get(f"INSTAGRAM_ACCESS_TOKEN_{suffix}")
            or os.environ.get("INSTAGRAM_ACCESS_TOKEN"))


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    state["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _mark_scope(ok: bool) -> None:
    state = _load_state()
    was_ok = state.get("comments_scope_ok", True)
    # only write on a flip (or first run) — the state file is committed by the
    # workflow, and a timestamp-only change every 2h would be pure git churn.
    if STATE_PATH.exists() and was_ok == ok:
        return
    state["comments_scope_ok"] = ok
    _save_state(state)
    if was_ok and not ok:
        msg = ("⚠️ <b>NinniTales engage</b>: the IG token can't manage comments "
               "(instagram_business_manage_comments missing). The comment-keyword CTA "
               "is now DISABLED for new posts. Re-Connect Instagram in the "
               "connect-helper to re-enable it.")
        print(msg)
        if notify_telegram and notify_telegram.configured():
            notify_telegram.send_message(msg)


def _is_permission_error(r: requests.Response) -> bool:
    if r.status_code == 403:
        return True
    try:
        err = r.json().get("error", {})
    except ValueError:
        return False
    return err.get("code") in (10, 200, 803) or "permission" in str(err).lower()


def _due_rows() -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=REPLY_WINDOW_DAYS)
    out = []
    for r in ledger.load():
        if (r.get("platform") != "instagram"
                or r.get("engagement_cta") != "comment_keyword"
                or not r.get("keyword") or not r.get("bonus_content")):
            continue
        try:
            posted = datetime.strptime(r["posted_at"], "%Y-%m-%dT%H:%M:%SZ") \
                .replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if posted >= cutoff:
            out.append(r)
    return out


def _comments(token: str, media_id: str) -> list[dict] | None:
    """[{id, text, username}] for a post; None on a permission failure."""
    r = requests.get(f"{IG_GRAPH}/{media_id}/comments",
                     params={"fields": "id,text,username",
                             "access_token": token, "limit": 50}, timeout=30)
    if not r.ok:
        if _is_permission_error(r):
            return None
        print(f"  ⚠️  comments fetch failed for {media_id}: {r.text[:160]}")
        return []
    return r.json().get("data", []) or []


def _reply(token: str, comment_id: str, message: str) -> bool | None:
    """True posted, False failed, None = permission problem."""
    r = requests.post(f"{IG_GRAPH}/{comment_id}/replies",
                      data={"message": message, "access_token": token}, timeout=30)
    if r.ok:
        return True
    if _is_permission_error(r):
        return None
    print(f"  ⚠️  reply failed on {comment_id}: {r.text[:160]}")
    return False


def run(dry_run: bool = False) -> int:
    rows = _due_rows()
    if not rows:
        print("engage: no recent comment-keyword posts — nothing to do.")
        return 0
    replies_sent = 0
    for row in rows:
        if replies_sent >= MAX_REPLIES_PER_RUN:
            break
        media_id = row["video_id"]
        token = _token(row.get("account_id"))
        if not token:
            print(f"  ⚠️  {media_id}: no IG token in env — skipping")
            continue
        comments = _comments(token, media_id)
        if comments is None:
            _mark_scope(False)
            return 1
        keyword = row["keyword"].lower()
        replied = set(row.get("replied_comment_ids") or [])
        message = f"{row['bonus_content'].strip()}\n\n{THANKS}"
        new_replied = set(replied)
        for c in comments:
            if replies_sent >= MAX_REPLIES_PER_RUN:
                break
            if c["id"] in replied or keyword not in (c.get("text") or "").lower():
                continue
            who = c.get("username", "?")
            if dry_run:
                print(f"  [dry-run] would reply to @{who} on {media_id} "
                      f"(keyword {row['keyword']})")
                continue
            ok = _reply(token, c["id"], message)
            if ok is None:
                _mark_scope(False)
                return 1
            if ok:
                new_replied.add(c["id"])
                replies_sent += 1
                print(f"  💬 replied to @{who} on {media_id} (keyword {row['keyword']})")
        if not dry_run and new_replied != replied:
            ledger.update(media_id, platform="instagram",
                          replied_comment_ids=sorted(new_replied))
    if not dry_run:
        _mark_scope(True)   # a full pass without permission errors = scope is healthy
    print(f"engage: done — {replies_sent} repl{'y' if replies_sent == 1 else 'ies'} "
          f"across {len(rows)} post(s).")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Reply to keyword comments with bonus content.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show matches without posting replies.")
    raise SystemExit(run(ap.parse_args().dry_run))
