"""llm.py — the ONE place that knows which LLM provider the engine talks to.

Sep 4 2026: Azure access was lost and the pipeline stopped dead — every surface at once.
Chat and image creds were resolved inline in four different modules (generate_hook,
ghostwriter, formats/carousel, characters), each with its own `AZURE_OPENAI_*` fallback
chain, so "swap the provider" meant editing four files and hoping none was missed. That
is the lock-in this module removes: provider choice is now env config, not code.

Default provider is GOOGLE GEMINI via its OpenAI-compatibility layer, which speaks the
same `chat.completions` / `images.generations` shapes the code already used — so the call
sites did not change, only where they point. Gemini's Flash text models are free tier;
image generation is NOT free on any Gemini model (~$0.039/image on gemini-2.5-flash-image,
the cheapest), which is still well under gpt-image pricing.

Env (all optional — the defaults are a working Gemini setup):
  GEMINI_API_KEY     the key from aistudio.google.com/apikey   ← the only REQUIRED one
  LLM_BASE_URL       OpenAI-compatible base URL (default: Gemini's)
  LLM_CHAT_MODEL     default "gemini-3.8-flash"        (free tier)
  LLM_IMAGE_MODEL    default "gemini-2.5-flash-image"  (cheapest image model)

To move to any other OpenAI-compatible provider (OpenAI direct, Groq, a local vLLM,
Azure again) set LLM_BASE_URL + LLM_API_KEY + the two model names. No code change.
"""

from __future__ import annotations

import os

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_CHAT_MODEL = "gemini-3.8-flash"
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"


def api_key() -> str | None:
    """The provider key. GEMINI_API_KEY is the name the setup docs tell you to set."""
    return (os.environ.get("LLM_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY"))


def base_url() -> str:
    return os.environ.get("LLM_BASE_URL", GEMINI_BASE).rstrip("/")


def chat_model() -> str:
    return os.environ.get("LLM_CHAT_MODEL", DEFAULT_CHAT_MODEL)


def image_model() -> str:
    return os.environ.get("LLM_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)


def configured() -> bool:
    """True when a key is present — lets callers degrade instead of raising."""
    return bool(api_key())


def client():
    """An OpenAI-SDK client pointed at the configured provider.

    Gemini's compatibility layer accepts the same `chat.completions.create(...)` calls
    (including `response_format={"type": "json_object"}`) the Azure client took, so every
    existing prompt and call site works unchanged.
    """
    from openai import OpenAI
    key = api_key()
    if not key:
        raise RuntimeError(
            "no LLM key — set GEMINI_API_KEY (get one free at "
            "https://aistudio.google.com/apikey), or point LLM_BASE_URL + LLM_API_KEY "
            "at another OpenAI-compatible provider.")
    return OpenAI(api_key=key, base_url=base_url())


def image_creds() -> tuple[str, str]:
    """(base_url, key) for the raw REST image calls that don't go through the SDK."""
    key = api_key()
    if not key:
        raise RuntimeError("no LLM key — set GEMINI_API_KEY for image generation.")
    return base_url(), key
