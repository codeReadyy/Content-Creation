"""niches.py — read/modify content settings in config/niches/<niche>.yml from the helper.

Keeps the "no hand-edited YAML" promise for niche-level content options too (today: the
Instagram carousel cover style). ruamel round-trip preserves the file's header comments +
layout, and what it writes stays valid YAML the engine reads with PyYAML.

Like accounts.py, this is decoupled — it only writes a file the engine already reads.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

import config

# Cover styles the engine's carousel format understands (formats/carousel.py).
COVER_STYLES = ["realistic", "anime"]
DEFAULT_COVER_STYLE = "anime"


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def _path(niche: str) -> Path:
    return config.TARGET_NICHES_DIR / f"{niche}.yml"


def get_cover_style(niche: str) -> str:
    p = _path(niche)
    if not p.exists():
        return DEFAULT_COVER_STYLE
    data = _yaml().load(p.read_text()) or {}
    style = data.get("carousel_cover_style", DEFAULT_COVER_STYLE)
    return style if style in COVER_STYLES else DEFAULT_COVER_STYLE


def set_cover_style(niche: str, style: str) -> bool:
    if style not in COVER_STYLES:
        return False
    p = _path(niche)
    if not p.exists():
        return False
    y = _yaml()
    data = y.load(p.read_text()) or {}
    data["carousel_cover_style"] = style
    with p.open("w") as f:
        y.dump(data, f)
    return True
