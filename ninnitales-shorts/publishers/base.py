"""publishers/base.py — the Publisher registry, keyed by platform.

The orchestrator looks up a publisher by account.platform and checks
`publisher.accepts` against the format's `produces` before building/posting.
"""

from __future__ import annotations

import importlib

from core.models import Publisher

# Publisher modules to import so they self-register. Add new platforms here.
_MODULES = ["publishers.youtube", "publishers.instagram", "publishers.tiktok"]

_REGISTRY: dict[str, Publisher] = {}
_loaded = False


def register(pub: Publisher) -> Publisher:
    """Called by each publisher module at import time."""
    _REGISTRY[pub.platform] = pub
    return pub


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    for mod in _MODULES:
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            pass
    _loaded = True


def get(platform: str) -> Publisher | None:
    _ensure_loaded()
    return _REGISTRY.get(platform)


def all_publishers() -> dict[str, Publisher]:
    _ensure_loaded()
    return dict(_REGISTRY)
