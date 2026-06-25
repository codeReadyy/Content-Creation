"""orchestrate.py — the config-driven daily run (supersedes daily.py).

Reads config/accounts.yml + config/niches/*.yml and, for each enabled account, fills
its scheduled slots: pick a format the platform accepts → build the Asset → tailor the
copy per platform → publish to that account (scheduled with a lead time) → log.

Token health is checked once up front and reported to Telegram every run; a dead token
aborts before wasting slots. Fully autonomous by default (gate: false); an account with
gate: true gets the old Telegram veto preview instead of an immediate schedule.

Modes:
  (default)    build + publish (scheduled) + ledger + Telegram
  --plan       print the decisions only — no media built, no publishing (fast wiring check)
  --dry-run    build the media into queue/ but do NOT publish or log
  --account ID restrict the run to one account

Run from the ninnitales-shorts/ directory (so sibling modules import).
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import notify_telegram
import run_pipeline
import token_doctor
from analytics import ledger
from copywriter import compose
from core import config, guardrails
from core.models import VIDEO, Account, BuildContext, Niche
from formats import base as formats
from publishers import base as publishers

HERE = Path(__file__).parent
ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def next_slots(times_et: list[str], now: datetime | None = None) -> list[str]:
    """The next upcoming slot per HH:MM ET time, as RFC3339 UTC strings.

    One slot per entry in times_et: the soonest future occurrence of each (today if
    >10min away, else tomorrow). Mirrors daily.next_slots but reads times from config.
    """
    now = now or datetime.now(ET)
    out: list[datetime] = []
    for hhmm in times_et:
        h, m = (int(x) for x in hhmm.split(":"))
        day = 0
        while True:
            t = datetime.combine(now.date() + timedelta(days=day), time(h, m), tzinfo=ET)
            if t > now + timedelta(minutes=10):
                out.append(t)
                break
            day += 1
    out.sort()
    return [t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") for t in out]


def _compatible_formats(account: Account, publisher) -> list[str]:
    """Account's formats the platform can actually post, in declared order."""
    compat = []
    for name in account.formats:
        fmt = formats.get(name)
        if fmt and fmt.produces in publisher.accepts:
            compat.append(name)
    return compat


def _plan_formats(compat: list[str], n: int) -> list[str]:
    """Round-robin the compatible formats across n slots (e.g. scraped,anime,scraped)."""
    return [compat[i % len(compat)] for i in range(n)] if compat else []


def _health_snapshot(h: dict) -> str:
    if not h["alive"]:
        return (f"❌ <b>YouTube token DEAD</b>\nReason: <code>{h['error']}</code>\n"
                f"From: {h['source']}\nFix: <code>python get_youtube_token.py</code> → "
                f"update .env AND the GitHub secret.")
    return (f"✅ <b>YouTube token healthy</b>\nChannel: {h.get('channel_title')}\n"
            f"Analytics: {'✅' if h.get('analytics_ok') else '⚠️ no'}   From: {h['source']}")


def _build_with_fallback(name: str, compat: list[str], niche: Niche,
                         ctx: BuildContext):
    """Build the chosen format; on failure fall back to the next compatible one."""
    order = [name] + [c for c in compat if c != name]
    for fname in order:
        fmt = formats.get(fname)
        if not fmt:
            continue
        asset = fmt.build(niche, ctx)
        if asset:
            return fname, asset
        print(f"  ↩️  {fname} produced nothing — trying fallback.")
    return None, None


def _veto_caption(title: str, account: Account, slot: str) -> str:
    slot_et = datetime.strptime(slot, "%Y-%m-%dT%H:%M:%SZ") \
        .replace(tzinfo=UTC).astimezone(ET)
    return (f"🌙 <b>NinniTales — scheduled (review)</b>\n\n<b>Title:</b> {title}\n"
            f"<b>Account:</b> {account.id}\n"
            f"<b>Goes live:</b> {slot_et:%a %b %d, %-I:%M %p} ET\n\n"
            f"Do nothing → it publishes.   ❌ Cancel   🔄 Cancel &amp; rebuild")


def run_account(account: Account, mode: str, rng: random.Random, tg: bool) -> dict:
    """Returns {slots, scheduled, alerts} for the run summary."""
    result = {"slots": 0, "scheduled": 0, "alerts": []}
    niche = config.load_niche(account.niche)
    publisher = publishers.get(account.platform)
    if not publisher:
        result["alerts"].append(f"{account.id}: no publisher for '{account.platform}'")
        return result
    compat = _compatible_formats(account, publisher)
    if not compat:
        result["alerts"].append(f"{account.id}: no compatible formats on {account.platform}")
        return result

    slots = next_slots(account.schedule_et)
    result["slots"] = len(slots)
    chosen = _plan_formats(compat, len(slots))
    ctas = sorted((HERE / niche.cta_dir).glob("cta*.mp4"))
    cookies = str(HERE / "cookies.txt") if (HERE / "cookies.txt").exists() else None
    avoid = run_pipeline.recent_titles(niche.dedup_window_days)
    base = len(ledger.load())

    print(f"\n=== {account.id} ({account.platform}, niche={account.niche}, "
          f"gate={account.gate}) ===")
    for i, (slot, fname) in enumerate(zip(slots, chosen)):
        slot_et = datetime.strptime(slot, "%Y-%m-%dT%H:%M:%SZ") \
            .replace(tzinfo=UTC).astimezone(ET)
        print(f"[{i+1}] {fname} → {slot_et:%a %b %d %-I:%M %p} ET")
        if mode == "plan":
            continue

        if not ctas and any(formats.get(f).produces == VIDEO for f in compat):
            result["alerts"].append(f"{account.id}: no CTA clips in {niche.cta_dir}")
            continue
        ctx = BuildContext(rng=rng, avoid_titles=avoid,
                           cta_path=ctas[(base + i) % len(ctas)] if ctas else None,
                           slot_index=i, cookies=cookies)
        used, asset = _build_with_fallback(fname, compat, niche, ctx)
        if not asset:
            result["alerts"].append(f"{account.id} [{fname}]: all formats failed")
            continue
        copy = compose(niche, account.platform, asset)
        avoid.append(copy.title)

        # Guardrails replace the human veto: a failure skips + alerts, never posts.
        verdict = guardrails.check(asset, copy, account.platform, niche)
        if not verdict.ok:
            alert = f"{account.id} [{used}] BLOCKED: {verdict.reason()}"
            print(f"    🚫 {alert}"); result["alerts"].append(alert); continue
        print(f"    title: {copy.title!r}  (theme={asset.theme}, source={asset.source})")

        if mode == "dry-run":
            print(f"    📦 built (no publish): {asset.path.name}")
            continue

        res = publisher.publish(asset, copy, account, publish_at=slot)
        if "error" in res:
            alert = f"{account.id} publish failed: {res['error']}"
            print(f"    ⚠️  {alert}"); result["alerts"].append(alert); continue
        ledger.log_upload(res["post_id"], copy.title, asset.theme, res["url"],
                          platform=account.platform, status="scheduled",
                          publish_at=slot, source=asset.source,
                          fmt=used, account_id=account.id,
                          product=account.product, niche=account.niche)
        result["scheduled"] += 1
        print(f"    ✅ scheduled: {res['url']}")
        # gate=true → send a veto preview so it can still be cancelled before going live.
        if account.gate and tg and account.platform == "youtube" and asset.kind == VIDEO:
            notify_telegram.send_video_preview(
                str(asset.path), _veto_caption(copy.title, account, slot),
                veto_token=res["post_id"])
    return result


def run(mode: str = "live", only_account: str | None = None) -> int:
    run_pipeline._load_env()
    run_pipeline.WORK_DIR.mkdir(exist_ok=True)
    run_pipeline.QUEUE_DIR.mkdir(exist_ok=True)
    rng = random.Random()

    # Token pre-flight (skip in plan mode — plan touches no credentials).
    tg = notify_telegram.configured()
    if mode != "plan":
        health = token_doctor.check()
        if tg:
            notify_telegram.send_message(f"🌙 <b>NinniTales run</b>\n\n{_health_snapshot(health)}")
        if not health["alive"]:
            print(f"❌ token dead ({health['error']}) — aborting.")
            return 1

    accounts = config.load_accounts()
    if only_account:
        accounts = [a for a in accounts if a.id == only_account]
        if not accounts:
            print(f"❌ no enabled account '{only_account}'."); return 1
    print(f"Mode: {mode}. Accounts: {[a.id for a in accounts]}")

    totals = {"slots": 0, "scheduled": 0, "alerts": []}
    for account in accounts:
        r = run_account(account, mode, rng, tg)
        totals["slots"] += r["slots"]
        totals["scheduled"] += r["scheduled"]
        totals["alerts"] += r["alerts"]

    print(f"\nDone. Scheduled {totals['scheduled']}/{totals['slots']}. "
          f"Alerts: {len(totals['alerts'])}.")
    if tg and mode == "live":
        icon = "✅" if totals["scheduled"] == totals["slots"] else (
            "⚠️" if totals["scheduled"] else "❌")
        lines = [f"{icon} <b>NinniTales run done</b> — scheduled "
                 f"{totals['scheduled']}/{totals['slots']} across {len(accounts)} account(s)."]
        if totals["alerts"]:
            lines.append("\n<b>Alerts:</b>")
            lines += [f"• {a}" for a in totals["alerts"][:10]]
        notify_telegram.send_message("\n".join(lines))
    return 0 if totals["scheduled"] or mode != "live" else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Config-driven multi-account content run.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--plan", action="store_true", help="Print decisions only; no build/publish.")
    g.add_argument("--dry-run", action="store_true", help="Build media but do not publish.")
    ap.add_argument("--account", default=None, help="Restrict to one account id.")
    args = ap.parse_args()
    mode = "plan" if args.plan else "dry-run" if args.dry_run else "live"
    raise SystemExit(run(mode, args.account))
