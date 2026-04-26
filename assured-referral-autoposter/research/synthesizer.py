"""
Content Brief Synthesizer — uses GPT-4o to turn research signals into a structured content brief.
Selects the best matching viral hook from hooks/1000_hooks_categorized.csv based on trending angle.
GPT-4o fills in the hook placeholders with relevant content.
"""

import csv
import json
import logging
import random
from datetime import date
from pathlib import Path
from typing import Optional

from openai import AzureOpenAI
from config.settings import Config

logger = logging.getLogger(__name__)

# Path to viral hooks CSV database
HOOKS_CSV_FILE = Path(__file__).parent.parent / "hooks" / "1000_hooks_categorized.csv"

# Category mapping: maps trending signals/themes to hook categories
# This helps select the most appropriate hook type based on content
CATEGORY_MAPPING = {
    # Trending themes -> Best hook categories
    "referral": ["Educational", "Authority", "Listicle"],
    "interview": ["Educational", "Listicle", "Authority"],
    "salary": ["Money", "Controversial", "Educational"],
    "negotiation": ["Money", "Authority", "Educational"],
    "resume": ["Educational", "Listicle", "Controversial"],
    "networking": ["Educational", "Relatable", "Authority"],
    "layoff": ["Relatable", "Educational", "Controversial"],
    "remote": ["Controversial", "Listicle", "Curiosity"],
    "job search": ["Educational", "Relatable", "Listicle"],
    "career change": ["Relatable", "Educational", "Curiosity"],
    "hiring": ["Authority", "Curiosity", "Educational"],
    "recruiter": ["Controversial", "Curiosity", "Authority"],
    "linkedin": ["Educational", "Listicle", "Authority"],
    "ai": ["Curiosity", "Educational", "Controversial"],
    "skills": ["Educational", "Listicle", "Authority"],

    # Sentiment signals -> Hook categories
    "high_frustration": ["Relatable", "Controversial", "Educational"],
    "success_stories_trending": ["Authority", "Curiosity", "Relatable"],
    "advice_seeking": ["Educational", "Listicle", "Authority"],

    # Content angles -> Hook categories
    "tactical_tips": ["Educational", "Listicle", "Authority"],
    "interview_mastery": ["Educational", "Listicle", "Authority"],
    "referral_power": ["Educational", "Authority", "Curiosity"],
    "empathy_and_solutions": ["Relatable", "Educational", "Listicle"],
    "success_transformation": ["Relatable", "Curiosity", "Authority"],
    "salary_negotiation": ["Money", "Educational", "Authority"],
    "layoff_recovery": ["Relatable", "Educational", "Curiosity"],
    "remote_work": ["Controversial", "Educational", "Listicle"],
}


def load_hooks_csv() -> dict[str, list[str]]:
    """
    Load viral hooks from the CSV database.
    Returns dict mapping category -> list of hook templates.
    """
    hooks_by_category = {}

    if not HOOKS_CSV_FILE.exists():
        logger.warning(f"Hooks CSV file not found: {HOOKS_CSV_FILE}")
        return hooks_by_category

    with open(HOOKS_CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            category = row.get("category", "").strip()
            hook = row.get("hook", "").strip()

            if category and hook:
                if category not in hooks_by_category:
                    hooks_by_category[category] = []
                # Avoid duplicates
                if hook not in hooks_by_category[category]:
                    hooks_by_category[category].append(hook)

    return hooks_by_category


def get_recommended_categories(signals: dict) -> list[str]:
    """
    Determine the best hook categories based on research signals.
    Returns ordered list of recommended categories.
    """
    category_scores = {}

    # Score based on combined themes
    for theme in signals.get("combined_themes", [])[:5]:
        theme_name = theme.get("theme", "").lower()
        score = theme.get("score", 1)

        for key, categories in CATEGORY_MAPPING.items():
            if key in theme_name:
                for i, cat in enumerate(categories):
                    # Higher weight for first category, decreasing
                    weight = (3 - i) * score
                    category_scores[cat] = category_scores.get(cat, 0) + weight

    # Score based on recommended angles
    for angle in signals.get("recommended_angles", [])[:3]:
        angle_name = angle.get("angle", "").lower()

        for key, categories in CATEGORY_MAPPING.items():
            if key in angle_name:
                for i, cat in enumerate(categories):
                    weight = 3 - i
                    category_scores[cat] = category_scores.get(cat, 0) + weight

    # Score based on sentiment signals
    reddit_data = signals.get("reddit", {})
    for sentiment in reddit_data.get("sentiment_signals", []):
        signal = sentiment.get("signal", "").lower()

        if signal in CATEGORY_MAPPING:
            for i, cat in enumerate(CATEGORY_MAPPING[signal]):
                weight = 2 - i * 0.5
                category_scores[cat] = category_scores.get(cat, 0) + weight

    # Sort by score
    sorted_categories = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)

    # Return top categories, default to Educational if none found
    if sorted_categories:
        return [cat for cat, score in sorted_categories[:3]]
    else:
        return ["Educational", "Listicle", "Relatable"]


def synthesize_brief(signals: dict) -> dict:
    """
    Synthesize a content brief from research signals using GPT-4o.
    Selects the best matching hook from the CSV database and fills placeholders.

    Args:
        signals: Output from gather_all_signals()

    Returns:
        Content brief dict:
        {
            "trending_angle": str,
            "hook_headline": str (filled template),
            "hook_category": str,
            "hook_template": str (original template),
            "keywords_to_use": list[str],
            "hashtags": list[str],
            "tone": str,
            "carousel_angle": str,
            "why_this_works_today": str
        }
    """
    # Load all hooks from CSV
    hooks_by_category = load_hooks_csv()

    if not hooks_by_category:
        logger.warning("No hooks loaded from CSV, using fallback")
        return _get_fallback_brief()

    # Get recommended categories based on signals
    recommended_categories = get_recommended_categories(signals)

    # Prepare signals summary for GPT
    signals_summary = _prepare_signals_summary(signals)

    # Prepare hook samples from recommended categories
    hook_samples = _prepare_hook_samples_from_categories(
        hooks_by_category, recommended_categories
    )

    # Call GPT-4o to synthesize the brief
    try:
        brief = _call_gpt_synthesizer(
            signals_summary, hook_samples, recommended_categories, hooks_by_category
        )
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
            lines.append(f"  - r/{p.get('subreddit', 'unknown')}: {p.get('title', '')[:80]}...")

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


def _prepare_hook_samples_from_categories(
    hooks_by_category: dict[str, list[str]],
    recommended_categories: list[str],
    samples_per_category: int = 8,
) -> str:
    """Prepare hook samples from recommended categories for GPT."""
    lines = ["AVAILABLE HOOK TEMPLATES BY CATEGORY:"]
    lines.append("(Select one template and fill in placeholders like (topic), (result), (skill), etc.)")
    lines.append("")

    # First show recommended categories
    for category in recommended_categories:
        if category in hooks_by_category:
            hooks = hooks_by_category[category]
            samples = random.sample(hooks, min(samples_per_category, len(hooks)))

            lines.append(f"\n{category.upper()} (Recommended):")
            for hook in samples:
                lines.append(f"  - {hook}")

    # Then show a few from other categories
    other_categories = [c for c in hooks_by_category.keys() if c not in recommended_categories]
    for category in other_categories[:2]:
        hooks = hooks_by_category[category]
        samples = random.sample(hooks, min(4, len(hooks)))

        lines.append(f"\n{category.upper()}:")
        for hook in samples:
            lines.append(f"  - {hook}")

    return "\n".join(lines)


def _call_gpt_synthesizer(
    signals_summary: str,
    hook_samples: str,
    recommended_categories: list[str],
    hooks_by_category: dict[str, list[str]],
) -> dict:
    """Call GPT-4o to synthesize the content brief and fill hook placeholders."""
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

CRITICAL TASK:
1. Analyze the trending signals to understand what's hot today
2. SELECT the best hook TEMPLATE from the provided samples
3. FILL IN the placeholders (topic), (result), (skill), (amount), (time), (action), (goal), etc. with SPECIFIC, RELEVANT content based on the trends
4. The filled hook should be punchy, specific, and scroll-stopping

PLACEHOLDER FILLING RULES:
- (topic) → specific career/job topic (e.g., "job referrals", "salary negotiation", "remote interviews")
- (result) → specific outcome (e.g., "land your dream job", "get 3x more interviews", "double your response rate")
- (skill) → specific skill (e.g., "networking", "interview prep", "LinkedIn optimization")
- (amount) → specific number/money (e.g., "$50K", "10 hours", "3 months")
- (time) → time period (e.g., "30 days", "2 weeks", "6 months")
- (action) → specific action (e.g., "cold applying", "networking on LinkedIn", "negotiating salary")
- (goal) → specific goal (e.g., "getting hired", "landing referrals", "acing interviews")
- (before) → before state (e.g., "rejected everywhere", "invisible to recruiters")
- (after) → after state (e.g., "3 job offers", "recruiters reaching out daily")
- (things) → what was analyzed (e.g., "job postings", "successful referrals", "LinkedIn profiles")
- (problem) → specific problem (e.g., "getting ghosted", "low response rates")
- (experience) → specific experience (e.g., "my job search", "100 interviews", "getting laid off")
- (change) → what changed (e.g., "I started asking for referrals", "I optimized my LinkedIn")
- (growth) → type of growth (e.g., "career growth", "network expansion", "skill development")
- (improvement) → area of improvement (e.g., "interview performance", "application success")
- (success) → type of success (e.g., "job search success", "networking success")
- (pain point) → specific pain (e.g., "endless applications", "recruiter ghosting")
- (common advice) → bad advice to counter (e.g., "apply to 100 jobs a day", "just be patient")
- (role) → your role/expertise (e.g., "recruiter", "career coach", "hiring manager")

OUTPUT FORMAT (strict JSON):
{
    "trending_angle": "specific topic to build carousel around today",
    "hook_template": "the EXACT template you selected from the samples",
    "hook_headline": "the FILLED hook with all placeholders replaced (max 15 words)",
    "hook_category": "Educational|Curiosity|Authority|Controversial|Money|Relatable|Listicle",
    "keywords_to_use": ["keyword1", "keyword2", "keyword3"],
    "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"],
    "tone": "inspirational|controversial|data-driven|storytelling|empathetic|tactical|bold",
    "carousel_angle": "specific angle for the carousel content",
    "why_this_works_today": "brief explanation of timeliness"
}
"""

    user_prompt = f"""Analyze these trending signals and create today's content brief.
Date: {date.today().isoformat()}

BRAND CONTEXT:
- AssuredReferral helps job seekers get referrals, recruiters find candidates, and referrers earn bonuses
- Tagline: "Get Referred. Get Hired. Get Rewarded."
- Focus areas: job search, referrals, interviews, networking, career growth

RECOMMENDED HOOK CATEGORIES (based on signals): {', '.join(recommended_categories)}

{signals_summary}

---

{hook_samples}

---

Based on the signals and available hook templates:
1. Choose the BEST hook template that matches today's trending angle
2. FILL IN all placeholders with specific, relevant content
3. Make the hook punchy and scroll-stopping (under 15 words)
4. Return the complete content brief JSON
"""

    response = client.chat.completions.create(
        model=Config.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.8,
        max_tokens=1000,
    )

    brief = json.loads(response.choices[0].message.content)

    # Validate required fields
    required_fields = [
        "trending_angle", "hook_headline", "hook_category",
        "keywords_to_use", "hashtags", "tone",
        "carousel_angle", "why_this_works_today"
    ]

    for field in required_fields:
        if field not in brief:
            logger.warning(f"Missing field in brief: {field}")
            brief[field] = _get_fallback_brief().get(field, "")

    # Validate hook_category
    valid_categories = {"Educational", "Curiosity", "Authority", "Controversial", "Money", "Relatable", "Listicle"}
    if brief.get("hook_category") not in valid_categories:
        brief["hook_category"] = recommended_categories[0] if recommended_categories else "Educational"

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
    hooks_by_category = load_hooks_csv()

    # Pick a random Educational hook and fill it
    if "Educational" in hooks_by_category and hooks_by_category["Educational"]:
        template = random.choice(hooks_by_category["Educational"])
        # Simple placeholder filling for fallback
        filled_hook = template.replace("(topic)", "job referrals")
        filled_hook = filled_hook.replace("(result)", "land your dream job")
        filled_hook = filled_hook.replace("(skill)", "networking")
        filled_hook = filled_hook.replace("(goal)", "getting hired faster")
    else:
        template = "Here's what no one tells you about (topic)"
        filled_hook = "Here's what no one tells you about job referrals"

    return {
        "trending_angle": "The power of referrals in today's job market",
        "hook_template": template,
        "hook_headline": filled_hook,
        "hook_category": "Educational",
        "keywords_to_use": ["referral", "job search", "networking", "hiring"],
        "hashtags": [
            "#JobSearch", "#CareerTips", "#Referrals",
            "#Networking", "#HiringNow", "#CareerAdvice", "#JobHunt"
        ],
        "tone": "educational",
        "carousel_angle": "Why referrals outperform cold applications",
        "why_this_works_today": "Referrals remain the most effective job search strategy",
    }


def get_hooks_stats() -> dict:
    """Get statistics about the hooks database."""
    hooks_by_category = load_hooks_csv()

    stats = {
        "total_hooks": 0,
        "categories": {},
        "unique_hooks_per_category": {},
    }

    for category, hooks in hooks_by_category.items():
        stats["categories"][category] = len(hooks)
        stats["total_hooks"] += len(hooks)
        stats["unique_hooks_per_category"][category] = len(set(hooks))

    return stats


if __name__ == "__main__":
    # Test the synthesizer with mock signals
    import logging
    logging.basicConfig(level=logging.INFO)

    # Load and display hook stats
    stats = get_hooks_stats()
    print(f"Hooks database stats:")
    print(f"  Total hooks: {stats['total_hooks']}")
    print(f"  Categories: {stats['categories']}")

    # Test category recommendation
    mock_signals = {
        "combined_themes": [
            {"theme": "referral", "score": 10, "sources": ["google_trends", "reddit"]},
            {"theme": "interview", "score": 8, "sources": ["reddit"]},
            {"theme": "salary", "score": 5, "sources": ["web_search"]},
        ],
        "recommended_angles": [
            {
                "angle": "referral_power",
                "description": "Highlight the power of referrals",
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

    print("\nRecommended categories for mock signals:")
    categories = get_recommended_categories(mock_signals)
    print(f"  {categories}")

    print("\nSynthesizing brief from mock signals...")
    brief = synthesize_brief(mock_signals)
    print(json.dumps(brief, indent=2))
