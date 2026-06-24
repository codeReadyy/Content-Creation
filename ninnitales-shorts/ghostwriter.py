"""ghostwriter.py — the AI copywriter that titles & describes a GENERATED Short.

Templates make every post a clone (same title, same caption, every day), which
reads as spam to YouTube and to parents. The ghostwriter replaces that for the
ANIME / generated path: it's an LLM given today's *situation* and asked to make a
call —

  • the keyword THEMES we rank on (search-first buckets), with example queries
  • theme WEIGHTS from analytics/winners.json (what earned views so far)
  • how the LAST 1-2 measured Shorts actually performed (views/likes/search)
  • the titles we've used RECENTLY, which it must NOT repeat

It returns a fresh search-first title + a real value-list (delivered through the
existing run_pipeline._desc wrapper, so the brand format and the soft NinniTales
link stay consistent while the words are always new). On any failure it returns
None and the caller falls back to the template chooser (which now dedups too).

Scraped Shorts keep using the templates — by design, they're fine for now.

Env: AZURE_OPENAI_API_KEY / _ENDPOINT / _API_VERSION + NINNITALES_CHAT_DEPLOYMENT
(falls back to AZURE_OPENAI_CHAT_DEPLOYMENT) — same creds generate_hook.py uses.
"""

import json
import os
import random

from openai import AzureOpenAI

import run_pipeline

# Search-first keyword buckets the ghostwriter may write for, with the kind of
# query a parent actually types. Mirrors the themes in run_pipeline.POSTS so
# analyze.py can keep attributing views back to them.
THEMES = {
    "sleep_fast": "how to get toddler to sleep faster",
    "wont_sleep": "toddler won't sleep at night",
    "bedtime_routine": "toddler bedtime routine that works",
    "through_night": "help baby sleep through the night",
    "make_sleep": "tricks to make kids fall asleep",
    "calm_before_bed": "calm an overtired toddler before bed",
    "bedtime_stories": "bedtime stories to put kids to sleep",
}

SYSTEM = """You are the ghostwriter for NinniTales — an app where a parent records
~90 seconds of their voice ONCE, and the app then narrates bedtime stories in the
parent's OWN voice so their young child falls asleep to it, anywhere (even when the
parent is away). The buyer is the exhausted PARENT.

Your job: write the YouTube Short's metadata so it (1) gets FOUND in search and
(2) actually helps, so parents save and rewatch it.

Hard rules:
- TITLE leads with the exact phrase a parent would TYPE into YouTube search, in the
  first ~40 characters (mobile truncates). A listicle shape ("5 ways to ...",
  "4 things ...") works best. <= 70 characters. NO emojis in the title.
- Give REAL, usable bedtime advice in 4-6 short list items.
- ONE item (the 2nd or 3rd) is the NinniTales method in plain human words — e.g.
  "play a bedtime story in your own recorded voice" — woven in, NEVER a sales pitch.
- Pick a "theme" from the allowed list that matches the title's intent.
- Be genuinely DIFFERENT from the recently-used titles you are given — different
  angle, number, and wording. Do not paraphrase them.

Return ONLY JSON:
{
  "theme": "<one of the allowed theme keys>",
  "title": "<search-first listicle title>",
  "steps": ["item 1", "item 2 (the NinniTales one)", "item 3", "..."],
  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"]
}"""


def _client() -> AzureOpenAI:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    if not key or not endpoint:
        raise RuntimeError("AZURE_OPENAI_API_KEY / _ENDPOINT not set")
    return AzureOpenAI(api_key=key, azure_endpoint=endpoint, api_version=version)


def _recent_performance(limit: int = 2) -> list[dict]:
    """The last `limit` finalized Shorts with their measured numbers."""
    finalized = [r for r in run_pipeline.ledger.load()
                 if r.get("finalized") and r.get("views") is not None]
    finalized.sort(key=lambda r: r.get("measured_at") or r.get("posted_at") or "",
                   reverse=True)
    out = []
    for r in finalized[:limit]:
        out.append({
            "title": r.get("title"),
            "theme": r.get("theme"),
            "views": r.get("views"),
            "likes": r.get("likes"),
            "search_views": r.get("search_views"),
        })
    return out


def _theme_weights() -> dict:
    """Per-theme avg search-driven views from winners.json (empty until measured)."""
    if not run_pipeline.WINNERS_PATH.exists():
        return {}
    try:
        return json.loads(run_pipeline.WINNERS_PATH.read_text()).get("theme_weights", {})
    except (json.JSONDecodeError, ValueError, AttributeError):
        return {}


def _user_prompt(avoid_titles: list[str]) -> str:
    perf = _recent_performance()
    weights = _theme_weights()
    themes_block = "\n".join(f'- {k}: parents search "{v}"' for k, v in THEMES.items())
    weights_block = (json.dumps(weights, indent=2) if weights
                     else "(no measured data yet — explore freely)")
    perf_block = (json.dumps(perf, indent=2) if perf
                  else "(nothing measured yet)")
    avoid_block = ("\n".join(f"- {t}" for t in avoid_titles)
                   if avoid_titles else "(none yet)")
    note = ("\nNote: search_views are null/0 — the Analytics scope isn't live yet, so "
            "treat the weights as WEAK signal (tiny samples). Favor a proven theme only "
            "slightly; keep exploring other themes.")
    return (
        "Allowed themes (key: what parents type):\n"
        f"{themes_block}\n\n"
        "Theme weights so far (avg search-driven views per theme):\n"
        f"{weights_block}\n\n"
        "How the last 1-2 Shorts actually performed:\n"
        f"{perf_block}{note}\n\n"
        "Titles already used recently — DO NOT repeat or paraphrase these:\n"
        f"{avoid_block}\n\n"
        "Write today's Short metadata as JSON only."
    )


def _norm(title: str) -> str:
    return " ".join((title or "").lower().split()).rstrip(".!?")


def write_post(rng: random.Random | None = None,
               avoid_titles: list[str] | None = None,
               attempts: int = 4) -> dict | None:
    """Write a fresh {title, description, theme, tags} for a generated Short.

    Returns None on any failure so the caller can fall back to choose_post().
    """
    avoid = list(avoid_titles or [])
    avoid_norm = {_norm(t) for t in avoid}
    try:
        client = _client()
    except RuntimeError as e:
        print(f"  ⚠️  ghostwriter: {e} — falling back to template.")
        return None
    deployment = (os.environ.get("NINNITALES_CHAT_DEPLOYMENT")
                  or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT"))

    for i in range(attempts):
        try:
            resp = client.chat.completions.create(
                model=deployment,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": _user_prompt(avoid)}],
                temperature=1.0,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            print(f"  ⚠️  ghostwriter call failed ({e}) — falling back to template.")
            return None
        choice = resp.choices[0]
        if choice.finish_reason == "content_filter" or not choice.message.content:
            print(f"  ⚠️  ghostwriter filtered (attempt {i + 1}/{attempts}), retrying...")
            continue
        try:
            data = json.loads(choice.message.content)
        except json.JSONDecodeError:
            continue

        title = (data.get("title") or "").strip()
        steps = [s.strip() for s in data.get("steps") or [] if s and s.strip()]
        theme = (data.get("theme") or "").strip()
        hashtags = [h.strip() for h in data.get("hashtags") or [] if h and h.strip()]
        if not title or len(steps) < 3 or theme not in THEMES:
            continue
        if _norm(title) in avoid_norm:
            print(f"  ↩️  ghostwriter reused a recent title — retrying for a fresh one.")
            avoid.append(title)  # tell the next attempt this one's taken too
            avoid_norm.add(_norm(title))
            continue

        tags_str = " ".join(hashtags) if hashtags else \
            "#toddlersleep #bedtime #momlife #parentinghacks #toddlermom"
        description = run_pipeline._desc(title, steps, tags_str)
        print(f"  ✍️  ghostwriter: {title!r} (theme={theme})")
        return {"title": title, "description": description, "theme": theme,
                "tags": run_pipeline.TAGS}

    print("  ⚠️  ghostwriter produced nothing usable — falling back to template.")
    return None
