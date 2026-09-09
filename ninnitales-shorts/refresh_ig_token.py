"""refresh_ig_token.py — keep the Instagram long-lived tokens alive, automatically.

Instagram-login long-lived tokens last ~60 days and DIE SILENTLY: nothing warns you, the
next run's pre-flight just aborts with "a required platform token is dead" and posting
stops until someone re-does the OAuth dance by hand. That is exactly what happened on
2026-08-26 — the token expired mid-flight and every IG run since failed.

Meta lets you re-extend a live token any time after it is 24h old (`ig_refresh_token`),
which resets the clock to a fresh ~60 days. So a weekly cron makes expiry unreachable:
the token is never more than 7 days into its 60-day life.

What this does, per enabled Instagram account in config/accounts.yml:
  1. refresh INSTAGRAM_ACCESS_TOKEN_<creds_env> against graph.instagram.com;
  2. write the new value to --out (JSON) so the workflow can `gh secret set` it — the
     token itself is NEVER printed (GitHub log-masked on sight);
  3. report days-to-expiry to Telegram, and shout if a refresh failed.

A refresh CANNOT resurrect an already-expired token — that needs a fresh browser login
via connect-helper. This script's job is to make sure we never get there.

Usage:
  python refresh_ig_token.py                 # refresh + report (no secret writing)
  python refresh_ig_token.py --out new.json  # + emit {SECRET_NAME: token} for CI
  python refresh_ig_token.py --check         # report health only, refresh nothing
"""

from __future__ import annotations

import argparse
import json
import os

import requests

import notify_telegram
import run_pipeline
import token_doctor
from core import config

GRAPH = "https://graph.instagram.com"
WARN_DAYS = 14          # shout below this many days of runway


def _secret_name(creds_env: str) -> str:
    return f"INSTAGRAM_ACCESS_TOKEN_{creds_env}"


def _token(creds_env: str) -> str | None:
    """The live token for this account — suffixed first, then the shared fallback."""
    return (os.environ.get(_secret_name(creds_env))
            or os.environ.get("INSTAGRAM_ACCESS_TOKEN"))


def refresh(token: str) -> tuple[str, int]:
    """Re-extend a live long-lived token → (new token, expires_in seconds)."""
    r = requests.get(f"{GRAPH}/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": token},
                     timeout=30)
    if not r.ok:
        try:
            msg = r.json().get("error", {}).get("message", r.text[:200])
        except ValueError:
            msg = r.text[:200]
        raise RuntimeError(msg)
    d = r.json()
    return d["access_token"], int(d.get("expires_in", 0))


def run(check_only: bool = False, out_path: str | None = None) -> int:
    run_pipeline._load_env()
    accounts = [a for a in config.load_accounts() if a.platform == "instagram"]
    if not accounts:
        print("no enabled Instagram accounts — nothing to refresh.")
        return 0

    lines: list[str] = []
    fresh: dict[str, str] = {}
    ok = True

    for a in accounts:
        name = _secret_name(a.creds_env)
        health = token_doctor.check_instagram(a.creds_env)
        if not health["alive"]:
            ok = False
            lines.append(f"❌ <b>{a.id}</b>: token DEAD — {health['error']}\n"
                         f"   → re-connect in connect-helper (a refresh can't revive it).")
            continue
        if check_only:
            lines.append(f"✅ <b>{a.id}</b>: alive (@{health['username']})")
            continue
        try:
            token, expires_in = refresh(_token(a.creds_env))
        except (RuntimeError, requests.RequestException) as e:
            ok = False
            lines.append(f"⚠️ <b>{a.id}</b>: refresh failed — {e}")
            continue
        fresh[name] = token
        days = expires_in // 86400
        icon = "✅" if days > WARN_DAYS else "⚠️"
        lines.append(f"{icon} <b>{a.id}</b>: refreshed (@{health['username']}) — "
                     f"valid {days} more days")

    report = "\n".join(lines)
    print(report.replace("<b>", "").replace("</b>", ""))
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(fresh, f)
        print(f"→ wrote {len(fresh)} refreshed secret(s) to {out_path}")
    if notify_telegram.configured():
        notify_telegram.send_message(f"🔑 <b>NinniTales — Instagram token</b>\n\n{report}")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Refresh Instagram long-lived tokens.")
    ap.add_argument("--check", action="store_true", help="Report health only; don't refresh.")
    ap.add_argument("--out", default=None,
                    help="Write {SECRET_NAME: new_token} JSON here for `gh secret set`.")
    args = ap.parse_args()
    raise SystemExit(run(check_only=args.check, out_path=args.out))
