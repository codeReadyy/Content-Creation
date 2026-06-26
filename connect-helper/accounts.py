"""accounts.py — read & modify the engine's config/accounts.yml from the helper.

The connect-helper is now the single place you manage accounts, so you never hand-edit
YAML. We use ruamel.yaml round-trip so the file's header comments + layout survive every
edit, and everything written stays valid YAML the engine reads with PyYAML.

Operations: list_accounts (for the UI), scaffold (on connect), set_format / set_enabled /
set_schedule, and remove (disconnect). Schedule times are written as QUOTED strings on
purpose — bare 08:00 is YAML base-60 (=480), so quotes keep them as clock times.
"""

from __future__ import annotations

import re
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

import config

# Formats each platform can post (the UI offers only these; mirrors the engine registry +
# Publisher.accepts — kept here as a small static list so the helper stays decoupled).
FORMATS_BY_PLATFORM = {
    "youtube": ["scraped_cta", "anime_cta"],
    "instagram": ["scraped_cta", "anime_cta", "carousel"],
    "tiktok": ["scraped_cta", "anime_cta"],
}
_DEFAULT_SCHEDULE = {
    "youtube": ["08:00", "12:30", "19:00"],
    "instagram": ["09:00", "18:00"],
    "tiktok": ["10:00", "20:00"],
}
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096                       # never wrap our long header/inline comments
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _flow(items: list) -> CommentedSeq:
    """A flow-style list so formats/schedule stay inline: [a, b]."""
    seq = CommentedSeq(items)
    seq.fa.set_flow_style()
    return seq


def _read(path: Path | None = None):
    path = path or config.TARGET_ACCOUNTS_YML
    y = _yaml()
    data = (y.load(path.read_text()) if path.exists() else None) or {}
    if not data.get("accounts"):
        data["accounts"] = CommentedSeq()
    return y, data, path


def _write(y: YAML, data, path: Path) -> None:
    with path.open("w") as f:
        y.dump(data, f)


def _find(data, acct_id: str):
    for a in data["accounts"]:
        if a.get("id") == acct_id:
            return a
    return None


def account_id(platform: str, suffix: str) -> str:
    return f"{platform}_{suffix}".lower()


def list_accounts(path: Path | None = None) -> list[dict]:
    _, data, _ = _read(path)
    out = []
    for a in data["accounts"]:
        out.append({
            "id": a.get("id"),
            "platform": a.get("platform"),
            "niche": a.get("niche"),
            "product": a.get("product"),
            "creds_env": a.get("creds_env"),
            "formats": [str(f) for f in (a.get("formats") or [])],
            "schedule_et": [str(t) for t in (a.get("schedule_et") or [])],
            "gate": bool(a.get("gate", False)),
            "enabled": bool(a.get("enabled", False)),
        })
    return out


def set_format(acct_id: str, fmt: str, path: Path | None = None) -> bool:
    y, data, p = _read(path)
    a = _find(data, acct_id)
    if a is None:
        return False
    a["formats"] = _flow([fmt])
    _write(y, data, p)
    return True


def set_enabled(acct_id: str, enabled: bool, path: Path | None = None) -> bool:
    y, data, p = _read(path)
    a = _find(data, acct_id)
    if a is None:
        return False
    a["enabled"] = bool(enabled)
    _write(y, data, p)
    return True


def set_schedule(acct_id: str, times: list[str], path: Path | None = None) -> bool:
    y, data, p = _read(path)
    a = _find(data, acct_id)
    if a is None:
        return False
    a["schedule_et"] = _flow([DQ(t) for t in times])
    _write(y, data, p)
    return True


def remove(acct_id: str, path: Path | None = None) -> bool:
    y, data, p = _read(path)
    lst = data["accounts"]
    for i, a in enumerate(lst):
        if a.get("id") == acct_id:
            del lst[i]                    # in place → preserves the other items' style
            _write(y, data, p)
            return True
    return False


def scaffold(platform: str, suffix: str, *, identity: str = "",
             path: Path | None = None) -> tuple[bool, str]:
    """Append a new (enabled:false) account block for (platform, suffix). Idempotent."""
    y, data, p = _read(path)
    acct_id = account_id(platform, suffix)
    if _find(data, acct_id) is not None:
        return False, acct_id
    formats = FORMATS_BY_PLATFORM.get(platform, ["scraped_cta"])
    schedule = _DEFAULT_SCHEDULE.get(platform, ["09:00", "18:00"])
    blk = CommentedMap()
    blk["id"] = acct_id
    blk["platform"] = platform
    blk["product"] = config.DEFAULT_PRODUCT
    blk["niche"] = config.DEFAULT_NICHE
    blk["creds_env"] = suffix
    blk["formats"] = _flow([formats[0]])
    blk["schedule_et"] = _flow([DQ(t) for t in schedule])
    blk["gate"] = False
    blk["enabled"] = False
    data["accounts"].append(blk)
    _write(y, data, p)
    return True, acct_id
