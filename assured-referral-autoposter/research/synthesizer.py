"""
Content Brief Synthesizer — uses GPT-4o to turn research signals into a structured content brief.
Selects the best matching viral hook from hooks/viral_hooks.txt based on trending angle.
"""

import json
import logging
import random
from datetime import date
from pathlib import Path
from typing import Optional

from openai import AzureOpenAI
from config.settings import Config

logger = logging.getLogger(__name__)

# Path to viral hooks database
HOOKS_FILE = Path(__file__).parent.parent / "hooks" / "viral_hooks.txt"


def load_hooks() -> list[dict]:
    """
    Load viral hooks from the hooks database file.
    Returns list of dicts with type, tone, and hook text.
    """
    hooks = []

    if not HOOKS_FILE.exists():
        logger.warning(f"Hooks file not found: {HOOKS_FILE}")
        return hooks

    with open(HOOKS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            parts = line.split("|")
            if len(parts) == 3:
                hooks.append({
                    "type": parts[0].strip(),
                    "tone": parts[1].strip(),
                    "hook": parts[2].strip(),
                })

    return hooks


def filter_hooks(
    hooks: list[dict],
    hook_type: str = None,
    tone: str = None,
) -> list[dict]:
    """Filter hooks by type and/or tone."""
    filtered = hooks

    if hook_type:
        filtered = [h for h in filtered if h["type"] == hook_type]

    if tone:
        filtered = [h for h in filtered if h["tone"] == tone]

    return filtered


def synthesize_brief(signals: dict) -> dict:
    """
    Synthesize a content brief from research signals using GPT-4o.
    Selects the best matching hook from the hooks database.

    Args:
        signals: Output from gather_all_signals()

    Returns:
        Content brief dict:
        {
            "trending_angle": str,
            "hook_headline": str,
            "hook_type": str,
            "keywords_to_use": list[str],
            "hashtags": list[str],
            "tone": str,
            "carousel_angle": str,
            "why_this_works_today": str
        }
    """
    # Load all hooks
    all_hooks = load_hooks()

    if not all_hooks:
        logger.warning("No hooks loaded, using fallback")
        return _get_fallback_brief()

    # Prepare signals summary for GPT
    signals_summary = _prepare_signals_summary(signals)

    # Prepare hook samples by type for GPT to select from
    hook_samples = _prepare_hook_samples(all_hooks)

    # Call GPT-4o to synthesize the brief
    try:
        brief = _call_gpt_synthesizer(signals_summary, hook_samples, all_hooks)
        return brief
    except Exception as e:
        logger.error(f"GPT synthesizer failed: {e}")
        return _get_fallback_brief()


def _prepare_signals_summary(signals: dict) -> str:
    """Convert signals dict to a readable summary for GPT."""
    lines = []

    # Combined themes
    themes = signals.get("combined_themes", [])
    if themes:
        lines.append("TOP TRENDING THEMES:")
        for t in themes[:5]:
            sources = ", ".join(t.get("sources", []))
            lines.append(f"  - {t['theme']} (score: {t['score']}, sources: {sources})")

    # Recommended angles
    angles = signals.get("recommended_angles", [])
    if angles:
        lines.append("\nRECOMMENDED CONTENT ANGLES:")
        for a in angles[:3]:
            lines.append(f"  - {a['angle']}: {a['description']}")
            lines.append(f"    Why now: {a.get('why_now', 'trending')}")
            lines.append(f"    Hook type: {a.get('hook_type', 'any')}")
            lines.append(f"    Tone: {a.get('tone', 'any')}")

    # Reddit sentiment
    reddit = signals.get("reddit", {})
    sentiment = reddit.get("sentiment_signals", [])
    if sentiment:
        lines.append("\nMARKET SENTIMENT:")
        for s in sentiment:
            lines.append(f"  - {s['signal']}: {s['description']}")

    # Hot Reddit posts (titles only)
    hot_posts = reddit.get("hot_posts", [])
    if hot_posts:
        lines.append("\nTRENDING REDDIT DISCUSSIONS:")
        for p in hot_posts[:5]:
            lines.append(f"  - r/{p['subreddit']}: {p['title'][:80]}...")

    # Web search insights
    web = signals.get("web_search", {})
    insights = web.get("key_insights", [])
    if insights:
        lines.append("\nWEB SEARCH INSIGHTS:")
        for i in insights[:3]:
            lines.append(f"  - {i['topic']}: {i['insight'][:100]}...")

    # Google Trends
    gt = signals.get("google_trends", {})
    rising = gt.get("rising_queries", [])
    if rising:
        lines.append("\nRISING SEARCH QUERIES:")
        for r in rising[:5]:
            lines.append(f"  - {r['query']} ({r.get('value', 'rising')})")

    return "\n".join(lines)


def _prepare_hook_samples(hooks: list[dict], samples_per_type: int = 5) -> str:
    """Prepare hook samples organized by type for GPT."""
    lines = ["AVAILABLE HOOK TYPES AND EXAMPLES:"]

    hook_types = set(h["type"] for h in hooks)

    for hook_type in sorted(hook_types):
        type_hooks = [h for h in hooks if h["type"] == hook_type]
        samples = random.sample(type_hooks, min(samples_per_type, len(type_hooks)))

        lines.append(f"\n{hook_type.upper()}:")
        for h in samples:
            lines.append(f"  [{h['tone']}] {h['hook']}")

    return "\n".join(lines)


def _call_gpt_synthesizer(
    signals_summary: str,
    hook_samples: str,
    all_hooks: list[dict],
) -> dict:
    """Call GPT-4o to synthesize the content brief."""
    client = AzureOpenAI(
        api_key=Config.AZURE_OPENAI_API_KEY,
        azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
        api_version=Config.AZURE_OPENAI_API_VERSION,
    )

    system_prompt = """You are a viral content strategist for AssuredReferral — a platform that:
- Helps job seekers get warm referrals at dream companies
- Provides AI-powered candidate screening for recruiters
- Rewards referrers with bonuses for successful placements

Your job is to analyze trending signals and create a content brief for today's LinkedIn/Instagram carousel.

IMPORTANT RULES:
1. SELECT a hook from the provided hook samples — do NOT create new hooks
2. Match the hook to today's trending angle and sentiment
3. The hook_headline must be a DIRECT COPY from the samples (you can make minor adjustments for relevance)
4. Consider the market sentiment when choosing tone
5. Keywords should be trending terms that fit naturally in content
6. Hashtags should be relevant and popular (5-7 hashtags)

OUTPUT FORMAT (strict JSON):
{
    "trending_angle": "specific topic to build carousel around today",
    "hook_headline": "EXACT hook from samples (max 10 words)",
    "hook_type": "stat|question|controversy|story|list|myth|secret|warning",
    "keywords_to_use": ["keyword1", "keyword2", "keyword3"],
    "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"],
    "tone": "inspirational|controversial|data-driven|storytelling|empathetic|tactical|bold",
    "carousel_angle": "specific angle for the carousel content",
    "why_this_works_today": "brief explanation of timeliness"
}
"""

    user_prompt = f"""Analyze these trending signals and create today's content brief.
Date: {date.today().isoformat()}

{signals_summary}

---

{hook_samples}

---

Based on the signals and available hooks, create the content brief JSON.
Choose a hook that MATCHES the trending angle and market sentiment.
"""

    response = client.chat.completions.create(
        model=Config.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=800,
    )

    brief = json.loads(response.choices[0].message.content)

    # Validate required fields
    required_fields = [
        "trending_angle", "hook_headline", "hook_type",
        "keywords_to_use", "hashtags", "tone",
        "carousel_angle", "why_this_works_today"
    ]

    for field in required_fields:
        if field not in brief:
            logger.warning(f"Missing field in brief: {field}")
            brief[field] = _get_fallback_brief().get(field, "")

    # Validate hook_type
    valid_types = {"stat", "question", "controversy", "story", "list", "myth", "secret", "warning"}
    if brief.get("hook_type") not in valid_types:
        brief["hook_type"] = "question"

    # Validate tone
    valid_tones = {"inspirational", "controversial", "data-driven", "storytelling", "empathetic", "tactical", "bold"}
    if brief.get("tone") not in valid_tones:
        brief["tone"] = "inspirational"

    # Ensure hashtags start with #
    brief["hashtags"] = [
        tag if tag.startswith("#") else f"#{tag}"
        for tag in brief.get("hashtags", [])
    ]

    return brief


def _get_fallback_brief() -> dict:
    """Fallback brief when synthesis fails."""
    # Load hooks and pick a random good one
    hooks = load_hooks()
    stat_hooks = [h for h in hooks if h["type"] == "stat" and h["tone"] in ("bold", "data-driven")]

    if stat_hooks:
        selected_hook = random.choice(stat_hooks)
        hook_headline = selected_hook["hook"]
        hook_type = selected_hook["type"]
        tone = selected_hook["tone"]
    else:
        hook_headline = "80% of jobs are never posted online."
        hook_type = "stat"
        tone = "bold"

    return {
        "trending_angle": "The power of referrals in today's job market",
        "hook_headline": hook_headline,
        "hook_type": hook_type,
        "keywords_to_use": ["referral", "job search", "networking", "hiring"],
        "hashtags": [
            "#JobSearch", "#CareerTips", "#Referrals",
            "#Networking", "#HiringNow", "#CareerAdvice", "#JobHunt"
        ],
        "tone": tone,
        "carousel_angle": "Why referrals outperform cold applications",
        "why_this_works_today": "Referrals remain the most effective job search strategy",
    }


def get_hook_for_angle(
    angle: str,
    hook_type: str = None,
    tone: str = None,
) -> str:
    """
    Get a matching hook for a specific angle.
    Useful for manual hook selection.
    """
    hooks = load_hooks()

    # Filter by type and tone if specified
    filtered = filter_hooks(hooks, hook_type, tone)

    if not filtered:
        filtered = hooks

    # Simple keyword matching
    angle_words = set(angle.lower().split())
    scored_hooks = []

    for hook in filtered:
        hook_words = set(hook["hook"].lower().split())
        overlap = len(angle_words & hook_words)
        scored_hooks.append((overlap, hook))

    # Sort by overlap score
    scored_hooks.sort(key=lambda x: x[0], reverse=True)

    if scored_hooks:
        return scored_hooks[0][1]["hook"]

    # Random fallback
    return random.choice(filtered)["hook"] if filtered else "Your job search strategy needs an upgrade."


if __name__ == "__main__":
    # Test the synthesizer with mock signals
    import logging
    logging.basicConfig(level=logging.INFO)

    # Load and display hook stats
    hooks = load_hooks()
    print(f"Loaded {len(hooks)} hooks")

    hook_types = {}
    for h in hooks:
        hook_types[h["type"]] = hook_types.get(h["type"], 0) + 1
    print(f"Hook types: {hook_types}")

    # Test with mock signals
    mock_signals = {
        "combined_themes": [
            {"theme": "referral", "score": 10, "sources": ["google_trends", "reddit"]},
            {"theme": "interview", "score": 8, "sources": ["reddit"]},
            {"theme": "layoff", "score": 5, "sources": ["web_search"]},
        ],
        "recommended_angles": [
            {
                "angle": "referral_power",
                "description": "Highlight the power of referrals",
                "hook_type": "stat",
                "tone": "bold",
                "why_now": "Referrals trending",
            }
        ],
        "reddit": {
            "sentiment_signals": [
                {
                    "signal": "advice_seeking",
                    "description": "High demand for actionable advice",
                }
            ],
            "hot_posts": [
                {"subreddit": "jobs", "title": "Finally got a job through a referral!"},
            ],
        },
    }

    print("\nSynthesizing brief from mock signals...")
    brief = synthesize_brief(mock_signals)
    print(json.dumps(brief, indent=2))
