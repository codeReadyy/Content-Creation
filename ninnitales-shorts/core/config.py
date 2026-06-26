"""core/config.py — load the routing table + niche profiles into typed objects.

Config is the single source of truth: which accounts run which formats on what
schedule (config/accounts.yml), and the content profile per niche
(config/niches/<name>.yml). Nothing in the code decides "who gets what" — it's all
here, so an agent adding an account/niche edits YAML, never the orchestrator.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from core.models import Account, Niche

PKG_ROOT = Path(__file__).resolve().parent.parent      # ninnitales-shorts/
CONFIG_DIR = PKG_ROOT / "config"
ACCOUNTS_FILE = CONFIG_DIR / "accounts.yml"
NICHES_DIR = CONFIG_DIR / "niches"

# Niche fields we map explicitly; everything else in the YAML lands in Niche.extra.
_NICHE_FIELDS = {
    "name", "product", "brand_context", "ghostwriter_system", "themes", "tags",
    "waitlist_url", "cta_dir", "scraped_theme", "scraped_titles",
    "scraped_description", "default_hashtags", "min_sample_per_theme",
    "explore_rate", "dedup_window_days",
}
_ACCOUNT_FIELDS = {
    "id", "platform", "product", "niche", "creds_env", "formats", "schedule_et",
    "gate", "enabled",
}


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping, got {type(data).__name__}")
    return data


@lru_cache(maxsize=None)
def load_niche(name: str) -> Niche:
    """Read config/niches/<name>.yml into a Niche (cached)."""
    data = _load_yaml(NICHES_DIR / f"{name}.yml")
    data.setdefault("name", name)
    known = {k: data[k] for k in _NICHE_FIELDS if k in data}
    extra = {k: v for k, v in data.items() if k not in _NICHE_FIELDS}
    missing = {"product", "brand_context", "ghostwriter_system", "themes", "tags",
               "waitlist_url", "cta_dir"} - known.keys()
    if missing:
        raise ValueError(f"niche '{name}' missing required fields: {sorted(missing)}")
    return Niche(extra=extra, **known)


def load_accounts(include_disabled: bool = False) -> list[Account]:
    """Read config/accounts.yml into a list of Account objects."""
    data = _load_yaml(ACCOUNTS_FILE)
    rows = data.get("accounts") or []
    out: list[Account] = []
    for row in rows:
        known = {k: row[k] for k in _ACCOUNT_FIELDS if k in row}
        extra = {k: v for k, v in row.items() if k not in _ACCOUNT_FIELDS}
        acct = Account(extra=extra, **known)
        if acct.enabled or include_disabled:
            out.append(acct)
    return out


def get_account(account_id: str) -> Account:
    for a in load_accounts(include_disabled=True):
        if a.id == account_id:
            return a
    raise KeyError(f"no account '{account_id}' in {ACCOUNTS_FILE}")
