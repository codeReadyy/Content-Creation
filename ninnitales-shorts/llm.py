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
                     NOTE: the free tier is 20 requests/day/model and image generation
                     has no free tier at all — this pipeline needs BILLING enabled on
                     the Google Cloud project behind the key (~$9/mo, images dominate).
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

    RETRIES ARE SET HERE, not at the call sites. The callers' own retry loops only
    handle a content filter — a transient `503 high demand` or a `429` escaped them and
    killed the whole run (seen live on gemini-3.8-flash the first day). Free-tier Gemini
    serves those routinely, so the SDK's own backoff (it retries 408/409/429/5xx) is
    raised above its default of 2 and every call site inherits it at once. Kept modest
    on purpose: a FREE-TIER 429 is a daily-quota refusal (20 requests/day/model), not a
    blip, so retrying it hard just stalls the slot — worst case here is bounded at about
    4 x 90s per call rather than a cron hanging for a quarter of an hour.
    """
    from openai import OpenAI
    key = api_key()
    if not key:
        raise RuntimeError(
            "no LLM key — set GEMINI_API_KEY (get one free at "
            "https://aistudio.google.com/apikey), or point LLM_BASE_URL + LLM_API_KEY "
            "at another OpenAI-compatible provider.")
    return OpenAI(api_key=key, base_url=base_url(),
                  max_retries=int(os.environ.get("LLM_MAX_RETRIES", "4")),
                  timeout=float(os.environ.get("LLM_TIMEOUT", "90")))


def image_creds() -> tuple[str, str]:
    """(base_url, key) for the raw REST image calls that don't go through the SDK."""
    key = api_key()
    if not key:
        raise RuntimeError("no LLM key — set GEMINI_API_KEY for image generation.")
    return base_url(), key
