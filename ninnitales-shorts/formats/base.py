"""formats/base.py — the Format registry.

Each format module registers an instance by name. `get(name)` / `all_formats()` let
the orchestrator resolve a format from config without importing it directly.
"""

from __future__ import annotations

import importlib

from core.models import Format

# Format modules to import so they self-register. Add new formats here.
_MODULES = ["formats.scraped_cta", "formats.anime_cta", "formats.carousel"]

_REGISTRY: dict[str, Format] = {}
_loaded = False


def register(fmt: Format) -> Format:
    """Called by each format module at import time."""
    _REGISTRY[fmt.name] = fmt
    return fmt


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    for mod in _MODULES:
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            # A format not yet implemented (or whose optional deps are absent) simply
            # isn't available — the orchestrator skips accounts that ask for it.
            pass
    _loaded = True


def get(name: str) -> Format | None:
    _ensure_loaded()
    return _REGISTRY.get(name)


def all_formats() -> dict[str, Format]:
    _ensure_loaded()
    return dict(_REGISTRY)
