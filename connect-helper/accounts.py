"""accounts.py — scaffold a starter block in the engine's config/accounts.yml.

After a successful connect we append a ready-to-edit account block with `enabled: false`,
so the new account exists in the routing table but stays dark until the user picks a
format + schedule and flips it on. We append a TEXT block (not a YAML round-trip) on
purpose: accounts.yml is full of explanatory comments that a load→dump would strip.

Idempotent: if a block with the same `id` is already present, we leave the file alone.
"""

from __future__ import annotations

from pathlib import Path

import config

# Sensible default schedules per platform (ET); the user edits these afterwards.
_DEFAULT_SCHEDULE = {
    "youtube": '["08:00", "12:30", "19:00"]',
    "instagram": '["09:00", "18:00"]',
    "tiktok": '["10:00", "20:00"]',
}


def account_id(platform: str, suffix: str) -> str:
    """A stable, readable id derived from the platform + creds suffix."""
    return f"{platform}_{suffix}".lower()


def has_account(acct_id: str, path: Path | None = None) -> bool:
    path = path or config.TARGET_ACCOUNTS_YML
    if not path.exists():
        return False
    return f"id: {acct_id}" in path.read_text()


def scaffold(platform: str, suffix: str, *, identity: str = "",
             path: Path | None = None) -> tuple[bool, str]:
    """Append an enabled:false block for (platform, suffix). Returns (wrote?, acct_id)."""
    path = path or config.TARGET_ACCOUNTS_YML
    acct_id = account_id(platform, suffix)
    if has_account(acct_id, path):
        return False, acct_id

    schedule = _DEFAULT_SCHEDULE.get(platform, '["09:00", "18:00"]')
    note = f" ({identity})" if identity else ""
    block = f"""
  # --- scaffolded by connect-helper{note} — set `formats` + flip `enabled: true` to go live ---
  - id: {acct_id}
    platform: {platform}
    product: {config.DEFAULT_PRODUCT}
    niche: {config.DEFAULT_NICHE}
    creds_env: {suffix}
    formats: [scraped_cta]          # TODO pick ONE format for this account
    schedule_et: {schedule}
    gate: false
    enabled: false
"""
    text = path.read_text() if path.exists() else "accounts:\n"
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + block)
    return True, acct_id
