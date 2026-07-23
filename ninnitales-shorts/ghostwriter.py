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

# The title SHAPE is ASSIGNED in code (like the carousel's hook_type), never left to
# the LLM. Told a listicle "works best", GPT opened 82% of 72 Shorts with a digit and
# the last 30 straight were all "<N> <synonym> to <verb> your toddler ..." — one
# sameness fingerprint, and a title_shapes standing with a single arm to compare.
# Both of the channel's brand-title breakouts (1,121 and 913 views) were NOT listicles.
TITLE_SHAPES = ("listicle", "question", "mistake", "moment", "outcome")
TITLE_SHAPE_SPECS = {
    "listicle": ('a numbered promise of a concrete payoff — like "5 ways to calm an '
                 'overtired toddler". The title STARTS with the digit.'),
    "question": ('the question the parent would actually type at 9pm — like "Why does '
                 'my toddler fight sleep every single night?". Ends with a question '
                 'mark. NO number at the start.'),
    "mistake": ('names the thing they are probably doing wrong, direct "you" voice — '
                'like "The bedtime habit keeping your toddler awake" or "Stop rocking '
                'them to sleep". NO number at the start.'),
    "moment": ('drops the reader into the exact hard moment, present tense — like '
               '"It\'s 9pm and they\'re still asking for water". NO number at the start.'),
    "outcome": ('states the after-state they want, plainly — like "Asleep in 20 '
                'minutes, without the fight". NO number at the start.'),
}
SHAPE_MIN_SAMPLE = 3       # measured Shorts per shape before exploiting it
SHAPE_EXPLORE_RATE = 0.25  # share of picks kept uniform even after coverage


def _system(shape: str) -> str:
    return f"""You are the ghostwriter for NinniTales — an app where a parent records
~90 seconds of their voice ONCE, and the app then narrates bedtime stories in the
parent's OWN voice so their young child falls asleep to it, anywhere (even when the
parent is away). The buyer is the exhausted PARENT.

Your job: write the YouTube Short's metadata so it (1) stops the scroll in the Shorts
feed and (2) actually helps, so parents save and rewatch it.

Hard rules:
- TITLE SHAPE IS ASSIGNED — today's title must be a {shape} title:
  {TITLE_SHAPE_SPECS[shape]}
  Do not fall back to a numbered listicle unless the assigned shape IS listicle.
- The title must still read like something a parent would say or search, front-loaded
  in the first ~40 characters (mobile truncates). <= 70 characters. NO emojis.
- Give REAL, usable bedtime advice in 4-6 short list items.
- ONE item (the 2nd or 3rd) is the NinniTales method in plain human words — e.g.
  "play a bedtime story in your own recorded voice" — woven in, NEVER a sales pitch.
- Pick a "theme" from the allowed list that matches the title's intent.
- Be genuinely DIFFERENT from the recently-used titles you are given — different
  angle, subject and wording. Do not paraphrase them.

Return ONLY JSON:
{{
  "theme": "<one of the allowed theme keys>",
  "title": "<a {shape} title>",
  "steps": ["item 1", "item 2 (the NinniTales one)", "item 3", "..."],
  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"]
}}"""


def _shape_standings() -> dict:
    if not run_pipeline.WINNERS_PATH.exists():
        return {}
    try:
        return json.loads(run_pipeline.WINNERS_PATH.read_text()).get("title_shapes") or {}
    except (json.JSONDecodeError, ValueError, AttributeError):
        return {}


def pick_title_shape(rng: random.Random | None = None) -> str:
    """Assign today's title shape: cover every arm SHAPE_MIN_SAMPLE times, then
    explore/exploit on measured median score (percentile while suppressed)."""
    rng = rng or random
    stand = _shape_standings()
    under = [s for s in TITLE_SHAPES if (stand.get(s) or {}).get("n", 0) < SHAPE_MIN_SAMPLE]
    if under:
        return rng.choice(under)
    if rng.random() < SHAPE_EXPLORE_RATE:
        return rng.choice(list(TITLE_SHAPES))
    weights = [max(float((stand.get(s) or {}).get("median_score",
                                                  (stand.get(s) or {}).get("median_views", 0)) or 0), 0.5)
               for s in TITLE_SHAPES]
    return rng.choices(list(TITLE_SHAPES), weights)[0]


def _shape_complies(shape: str, title: str) -> bool:
    """Cheap structural check — the LLM obeys the spec or gets one corrective retry."""
    if shape not in TITLE_SHAPES or not title:
        return True
    digit_lead = title.strip()[:1].isdigit()
    if shape == "listicle":
        return digit_lead
    if shape == "question":
        return not digit_lead and title.strip().endswith("?")
    return not digit_lead


def _actual_shape(shape: str, title: str) -> str:
    """The shape that actually SHIPPED — the arm the standings must be told about.

    Only two shapes are structurally verifiable (a leading digit, a trailing '?'), so
    a disobedient title is relabelled by those; the three statement shapes are
    indistinguishable structurally, and the assignment is the best label we have.
    """
    if _shape_complies(shape, title):
        return shape
    if title.strip()[:1].isdigit():
        return "listicle"
    if title.strip().endswith("?"):
        return "question"
    return "outcome" if shape == "question" else shape


def _client() -> AzureOpenAI:
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
    if not key or not endpoint:
        raise RuntimeError("AZURE_OPENAI_API_KEY / _ENDPOINT not set")
    return AzureOpenAI(api_key=key, azure_endpoint=endpoint, api_version=version)


def _recent_performance(limit: int = 2, platform: str = "youtube") -> list[dict]:
    """The last `limit` finalized posts ON ONE PLATFORM with their measured numbers
    (the ledger is multi-platform now; an IG carousel's raw views shown as 'how the
    last Shorts performed' would mislead the writer)."""
    finalized = [r for r in run_pipeline.ledger.load()
                 if r.get("finalized") and r.get("views") is not None
                 and r.get("platform", "youtube") == platform]
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


def _theme_weights(platform: str = "youtube") -> dict:
    """Per-theme MEDIAN score from winners.json for ONE platform (scores are
    different units per platform, so they must never be read mixed).

    Pinterest has no API analytics yet (RSS mode) — its pins fall back to the
    YOUTUBE weights as a prior: same theme keys, and both KPIs measure search
    demand for the keyword. A stale pre-split winners.json falls back to the
    legacy mixed weights."""
    if not run_pipeline.WINNERS_PATH.exists():
        return {}
    try:
        data = json.loads(run_pipeline.WINNERS_PATH.read_text())
    except (json.JSONDecodeError, ValueError, AttributeError):
        return {}
    per = data.get("theme_weights_by_platform")
    if per is None:  # stale winners.json (pre per-platform)
        return data.get("theme_weights", {})
    weights = per.get(platform) or {}
    if not weights and platform == "pinterest":
        weights = per.get("youtube") or {}
    return weights


# The avoid list is built from a 3650-day dedup window, so it grows ~6 titles/day
# forever — 183 of them (~10KB) were being pasted into every call, burying the theme
# weights and recent-performance blocks that actually steer the writer. The most
# recent ones are the only ones a reader would notice repeating anyway.
AVOID_IN_PROMPT = 25


def _user_prompt(avoid_titles: list[str]) -> str:
    perf = _recent_performance()
    weights = _theme_weights()
    themes_block = "\n".join(f'- {k}: e.g. "{v}"' for k, v in THEMES.items())
    weights_block = (json.dumps(weights, indent=2) if weights
                     else "(no measured data yet — explore freely)")
    perf_block = (json.dumps(perf, indent=2) if perf
                  else "(nothing measured yet)")
    avoid_block = ("\n".join(f"- {t}" for t in avoid_titles[-AVOID_IN_PROMPT:])
                   if avoid_titles else "(none yet)")
    # The Jul-2026 audit measured search at ~3% of traffic and the Analytics scope has
    # never returned a single search-attributed view, so `search_views` silently falls
    # back to TOTAL views. Shorts wins come from feed retention — say so, rather than
    # telling the writer to optimize for a search signal nobody has ever observed.
    note = ("\nNote: these are TOTAL views, not search-attributed — YouTube's search "
            "scope has never reported for this channel, and search was ~3% of traffic "
            "when it was measurable. Shorts wins come from stopping the scroll, not "
            "from keyword matching. Samples are tiny, so favor a proven theme only "
            "slightly and keep exploring.")
    return (
        "Allowed themes (key: the kind of thing a parent says or searches):\n"
        f"{themes_block}\n\n"
        "Theme weights so far (median views per theme, YouTube only):\n"
        f"{weights_block}\n\n"
        "How the last 1-2 Shorts actually performed:\n"
        f"{perf_block}{note}\n\n"
        "Titles already used recently — DO NOT repeat or paraphrase these:\n"
        f"{avoid_block}\n\n"
        "Write today's Short metadata as JSON only."
    )


def _norm(title: str) -> str:
    return " ".join((title or "").lower().split()).rstrip(".!?")


# ── Pinterest pins ──────────────────────────────────────────────────────────────
# Pinterest is a SEARCH engine: parents type "toddler bedtime routine", "calming
# stories", "sleep tips" and pins surface for months. So a pin's title + description
# are keyword-first (like a YouTube Short title), but longer-lived and click-driven —
# the win is the OUTBOUND CLICK to ninnitales.com, not a like. This reuses the same
# research signals as write_post (themes, measured weights, recent performance, dedup)
# so Pinterest rides the SAME content loop as YouTube/Instagram.
PIN_SYSTEM = """You are the Pinterest ghostwriter for NinniTales — an app where a parent
records ~90 seconds of their voice ONCE, and the app then narrates bedtime stories in the
parent's OWN voice so their young child falls asleep to it, anywhere (even when the parent
is away). The buyer is the exhausted PARENT.

Pinterest is a SEARCH engine for parents. Your job: write ONE pin that (1) gets FOUND when
a parent searches bedtime/sleep topics and (2) makes them click through to the app.

Hard rules:
- TITLE: keyword-first, the exact phrase a parent would SEARCH, <= 100 characters,
  scannable and specific (e.g. "Toddler Bedtime Routine That Actually Works"). No emojis.
- DESCRIPTION: 300-500 characters, keyword-rich but natural and genuinely helpful — real
  bedtime advice a parent can use, woven with relevant search phrases. End with a soft,
  human CTA to try recording a bedtime story in your own voice (NinniTales) — never a hard
  sell. You may include 2-4 hashtags inline at the end.
- Weave the NinniTales idea in plain words ("play a bedtime story in your own recorded
  voice") as ONE helpful tip among others — not the whole pin.
- Pick a "theme" from the allowed list that matches the pin's intent, and a "board" from
  the allowed boards that best fits the topic.
- Be genuinely DIFFERENT from the recently-used titles you are given.

Return ONLY JSON:
{
  "theme": "<one allowed theme key>",
  "board": "<one allowed board name, verbatim>",
  "title": "<keyword-first pin title <=100 chars>",
  "description": "<300-500 char keyword-rich helpful description with a soft CTA>",
  "hashtags": ["#tag1", "#tag2", "#tag3"]
}"""


def _pin_user_prompt(themes: dict, boards: list[str], avoid_titles: list[str]) -> str:
    # Pinterest weights (falls back to YouTube's search medians as a prior while
    # RSS-mode pins have no analytics); recent perf likewise shows YouTube numbers.
    weights = _theme_weights("pinterest")
    perf = _recent_performance()
    themes_block = "\n".join(f'- {k}: parents search "{v}"' for k, v in themes.items())
    boards_block = "\n".join(f"- {b}" for b in boards) or "- Toddler Bedtime"
    weights_block = (json.dumps(weights, indent=2) if weights
                     else "(no measured data yet — explore freely)")
    perf_block = json.dumps(perf, indent=2) if perf else "(nothing measured yet)"
    avoid_block = ("\n".join(f"- {t}" for t in avoid_titles[-15:])
                   if avoid_titles else "(none yet)")
    return (
        "Allowed themes (key: what parents type):\n"
        f"{themes_block}\n\n"
        "Allowed boards (pick the best topical fit, name verbatim):\n"
        f"{boards_block}\n\n"
        "Theme weights so far (median search-driven views per theme; YouTube data "
        "doubles as the pin prior until Pinterest analytics unlock):\n"
        f"{weights_block}\n\n"
        "How recent posts performed:\n"
        f"{perf_block}\n\n"
        "Pin titles already used recently — DO NOT repeat or paraphrase these:\n"
        f"{avoid_block}\n\n"
        "Write today's pin as JSON only."
    )


def write_pin(rng: random.Random | None = None,
              avoid_titles: list[str] | None = None,
              themes: dict | None = None,
              boards: list[str] | None = None,
              attempts: int = 4) -> dict | None:
    """Write a fresh Pinterest pin {theme, board, title, description, hashtags}.

    Reuses the research signals (themes, measured weights, recent performance) and the
    dedup discipline of write_post, tuned for Pinterest SEO. Returns None on any failure
    so the caller (formats/pin.py) can fall back to its template pin.
    """
    themes = themes or THEMES
    boards = boards or []
    avoid = list(avoid_titles or [])
    avoid_norm = {_norm(t) for t in avoid}
    try:
        client = _client()
    except RuntimeError as e:
        print(f"  ⚠️  pin ghostwriter: {e} — falling back to template.")
        return None
    deployment = (os.environ.get("NINNITALES_CHAT_DEPLOYMENT")
                  or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT"))

    for i in range(attempts):
        try:
            resp = client.chat.completions.create(
                model=deployment,
                messages=[{"role": "system", "content": PIN_SYSTEM},
                          {"role": "user",
                           "content": _pin_user_prompt(themes, boards, avoid)}],
                temperature=1.0,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            print(f"  ⚠️  pin ghostwriter call failed ({e}) — falling back to template.")
            return None
        choice = resp.choices[0]
        if choice.finish_reason == "content_filter" or not choice.message.content:
            print(f"  ⚠️  pin ghostwriter filtered (attempt {i + 1}/{attempts}), retrying...")
            continue
        try:
            data = json.loads(choice.message.content)
        except json.JSONDecodeError:
            continue

        title = (data.get("title") or "").strip()
        desc = (data.get("description") or "").strip()
        theme = (data.get("theme") or "").strip()
        board = (data.get("board") or "").strip()
        hashtags = [h.strip() for h in data.get("hashtags") or [] if h and h.strip()]
        if not title or len(desc) < 80 or theme not in themes:
            continue
        if _norm(title) in avoid_norm:
            print("  ↩️  pin ghostwriter reused a recent title — retrying for a fresh one.")
            avoid.append(title)
            avoid_norm.add(_norm(title))
            continue
        # Snap the board onto an allowed one (case-insensitive); caller may still rotate.
        if boards:
            match = next((b for b in boards if b.lower() == board.lower()), None)
            board = match or rng_choice(boards, rng)
        print(f"  ✍️  pin ghostwriter: {title!r} (theme={theme}, board={board})")
        return {"theme": theme, "board": board, "title": title,
                "description": desc, "hashtags": hashtags}

    print("  ⚠️  pin ghostwriter produced nothing usable — falling back to template.")
    return None


def rng_choice(items: list, rng: random.Random | None):
    """random.choice that tolerates a None rng (uses the module default)."""
    return (rng or random).choice(items)


def write_post(rng: random.Random | None = None,
               avoid_titles: list[str] | None = None,
               attempts: int = 4,
               shape: str | None = None) -> dict | None:
    """Write a fresh {title, description, theme, tags, title_shape} for a Short.

    `shape` is ASSIGNED (defaults to pick_title_shape) and enforced — the writer gets
    one corrective retry if it ignores the shape, and the shape that actually shipped
    is returned so the ledger records the arm that ran, not the one we asked for.

    Returns None on any failure so the caller can fall back to choose_post().
    """
    avoid = list(avoid_titles or [])
    avoid_norm = {_norm(t) for t in avoid}
    shape = shape if shape in TITLE_SHAPES else pick_title_shape(rng)
    try:
        client = _client()
    except RuntimeError as e:
        print(f"  ⚠️  ghostwriter: {e} — falling back to template.")
        return None
    deployment = (os.environ.get("NINNITALES_CHAT_DEPLOYMENT")
                  or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT"))
    nudge: list[dict] = []

    for i in range(attempts):
        try:
            resp = client.chat.completions.create(
                model=deployment,
                messages=([{"role": "system", "content": _system(shape)},
                           {"role": "user", "content": _user_prompt(avoid)}] + nudge),
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
        # Exact-match dedup passed near-identical paraphrases on consecutive days.
        twin = run_pipeline.too_similar(title, avoid)
        if twin:
            print(f"  ↩️  ghostwriter paraphrased {twin!r} — retrying for a fresh angle.")
            avoid.append(title)
            avoid_norm.add(_norm(title))
            continue
        if not _shape_complies(shape, title) and not nudge:
            print(f"  ↻ {title!r} isn't a {shape} title — one corrective retry.")
            nudge = [{"role": "assistant", "content": choice.message.content},
                     {"role": "user",
                      "content": (f"That title is not a {shape} title. It must be: "
                                  f"{TITLE_SHAPE_SPECS[shape]} Rewrite the JSON.")}]
            continue

        tags_str = " ".join(hashtags) if hashtags else \
            "#toddlersleep #bedtime #momlife #parentinghacks #toddlermom"
        description = run_pipeline._desc(title, steps, tags_str)
        # Record the shape that SHIPPED. If the retry still disobeyed, the arm being
        # measured is whatever actually went out, or the standings learn a fiction.
        actual = _actual_shape(shape, title)
        print(f"  ✍️  ghostwriter: {title!r} (theme={theme}, shape={actual})")
        # steps ride along so the scraped path can burn a real tip on the clip
        # (the value beat) without re-parsing the description.
        return {"title": title, "description": description, "theme": theme,
                "tags": run_pipeline.TAGS, "steps": steps, "title_shape": actual}

    print("  ⚠️  ghostwriter produced nothing usable — falling back to template.")
    return None
