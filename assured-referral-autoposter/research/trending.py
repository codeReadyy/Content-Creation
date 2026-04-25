"""
Trending orchestrator — gathers signals from all research sources.
Combines Google Trends, Reddit, and Tavily web search into unified trending data.
"""

import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from research.sources.google_trends import get_google_trends
from research.sources.reddit_scraper import get_reddit_hot_posts
from research.sources.web_search import search_career_news

logger = logging.getLogger(__name__)


def gather_all_signals(
    include_google_trends: bool = True,
    include_reddit: bool = True,
    include_web_search: bool = True,
    timeout: int = 60,
) -> dict:
    """
    Gather trending signals from all configured research sources.
    Runs sources in parallel for faster execution.

    Args:
        include_google_trends: Whether to fetch Google Trends data
        include_reddit: Whether to fetch Reddit hot posts
        include_web_search: Whether to run Tavily web searches
        timeout: Maximum time to wait for all sources (seconds)

    Returns:
        Dict with combined signals from all sources:
        {
            "timestamp": "...",
            "google_trends": {...},
            "reddit": {...},
            "web_search": {...},
            "combined_themes": [...],
            "recommended_angles": [...]
        }
    """
    results = {
        "timestamp": datetime.now().isoformat(),
        "google_trends": None,
        "reddit": None,
        "web_search": None,
        "combined_themes": [],
        "recommended_angles": [],
        "errors": [],
    }

    # Define tasks to run
    tasks = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        if include_google_trends:
            tasks["google_trends"] = executor.submit(get_google_trends)

        if include_reddit:
            tasks["reddit"] = executor.submit(get_reddit_hot_posts)

        if include_web_search:
            tasks["web_search"] = executor.submit(search_career_news)

        # Collect results
        for name, future in tasks.items():
            try:
                results[name] = future.result(timeout=timeout)
                logger.info(f"Successfully fetched {name}")
            except Exception as e:
                logger.error(f"Failed to fetch {name}: {e}")
                results["errors"].append({"source": name, "error": str(e)})

    # Combine themes from all sources
    results["combined_themes"] = _combine_themes(results)

    # Generate recommended content angles
    results["recommended_angles"] = _generate_angles(results)

    return results


def _combine_themes(data: dict) -> list[dict]:
    """
    Extract and combine trending themes from all sources.
    Returns a ranked list of themes with source attribution.
    """
    themes = {}

    # From Google Trends
    if data.get("google_trends"):
        gt = data["google_trends"]

        # Rising queries
        for item in gt.get("rising_queries", []):
            query = item.get("query", "").lower()
            if query:
                themes[query] = themes.get(query, {"count": 0, "sources": []})
                themes[query]["count"] += 2  # Higher weight for rising
                if "google_trends" not in themes[query]["sources"]:
                    themes[query]["sources"].append("google_trends")

        # Top queries
        for item in gt.get("top_queries", []):
            query = item.get("query", "").lower()
            if query:
                themes[query] = themes.get(query, {"count": 0, "sources": []})
                themes[query]["count"] += 1
                if "google_trends" not in themes[query]["sources"]:
                    themes[query]["sources"].append("google_trends")

    # From Reddit
    if data.get("reddit"):
        rd = data["reddit"]

        # Top themes
        for item in rd.get("top_themes", []):
            theme = item.get("theme", "").lower()
            if theme:
                mentions = item.get("mentions", 1)
                themes[theme] = themes.get(theme, {"count": 0, "sources": []})
                themes[theme]["count"] += mentions
                if "reddit" not in themes[theme]["sources"]:
                    themes[theme]["sources"].append("reddit")

        # Extract themes from hot post titles
        for post in rd.get("hot_posts", [])[:10]:
            title = post.get("title", "").lower()
            for keyword in ["referral", "interview", "salary", "remote", "layoff", "hiring"]:
                if keyword in title:
                    themes[keyword] = themes.get(keyword, {"count": 0, "sources": []})
                    themes[keyword]["count"] += 1
                    if "reddit" not in themes[keyword]["sources"]:
                        themes[keyword]["sources"].append("reddit")

    # From Web Search
    if data.get("web_search"):
        ws = data["web_search"]

        # Extract from key insights
        for insight in ws.get("key_insights", []):
            topic = insight.get("topic", "").lower()
            # Extract key terms
            for keyword in ["referral", "skills", "ai", "remote", "hiring", "layoff"]:
                if keyword in topic or keyword in insight.get("insight", "").lower():
                    themes[keyword] = themes.get(keyword, {"count": 0, "sources": []})
                    themes[keyword]["count"] += 1
                    if "web_search" not in themes[keyword]["sources"]:
                        themes[keyword]["sources"].append("web_search")

    # Sort by count and format
    sorted_themes = sorted(themes.items(), key=lambda x: x[1]["count"], reverse=True)

    return [
        {
            "theme": theme,
            "score": data["count"],
            "sources": data["sources"],
            "multi_source": len(data["sources"]) > 1,
        }
        for theme, data in sorted_themes[:10]
    ]


def _generate_angles(data: dict) -> list[dict]:
    """
    Generate recommended content angles based on trending signals.
    Combines theme analysis with sentiment and engagement patterns.
    """
    angles = []

    # Check Reddit sentiment signals
    reddit_data = data.get("reddit", {})
    sentiment_signals = reddit_data.get("sentiment_signals", [])

    for signal in sentiment_signals:
        if signal.get("signal") == "high_frustration":
            angles.append({
                "angle": "empathy_and_solutions",
                "description": "Address common frustrations with actionable solutions",
                "hook_type": "question",
                "tone": "empathetic",
                "why_now": "High frustration in job market discussions",
            })

        if signal.get("signal") == "success_stories_trending":
            angles.append({
                "angle": "success_transformation",
                "description": "Share success stories and what made the difference",
                "hook_type": "story",
                "tone": "inspirational",
                "why_now": "Success stories getting high engagement",
            })

        if signal.get("signal") == "advice_seeking":
            angles.append({
                "angle": "tactical_tips",
                "description": "Provide specific, actionable career tips",
                "hook_type": "list",
                "tone": "authoritative",
                "why_now": "High demand for practical advice",
            })

    # Check top themes for angle opportunities
    combined_themes = data.get("combined_themes", [])

    for theme in combined_themes[:3]:
        theme_name = theme.get("theme", "")

        if "referral" in theme_name:
            angles.append({
                "angle": "referral_power",
                "description": "Highlight the power of referrals in job search",
                "hook_type": "stat",
                "tone": "data-driven",
                "why_now": f"'{theme_name}' trending across {len(theme.get('sources', []))} sources",
            })

        if "interview" in theme_name:
            angles.append({
                "angle": "interview_mastery",
                "description": "Interview tips and insider insights",
                "hook_type": "list",
                "tone": "tactical",
                "why_now": f"'{theme_name}' getting high attention",
            })

        if "salary" in theme_name or "negotiat" in theme_name:
            angles.append({
                "angle": "salary_negotiation",
                "description": "Salary negotiation strategies and frameworks",
                "hook_type": "stat",
                "tone": "bold",
                "why_now": f"Compensation discussions trending",
            })

        if "layoff" in theme_name:
            angles.append({
                "angle": "layoff_recovery",
                "description": "Bouncing back from layoffs, finding opportunities",
                "hook_type": "story",
                "tone": "empathetic",
                "why_now": "Layoff discussions active in the market",
            })

        if "remote" in theme_name or "hybrid" in theme_name:
            angles.append({
                "angle": "remote_work",
                "description": "Remote work strategies and opportunities",
                "hook_type": "controversy",
                "tone": "opinionated",
                "why_now": "Remote/hybrid work continues to be debated",
            })

    # Deduplicate by angle name
    seen_angles = set()
    unique_angles = []
    for angle in angles:
        if angle["angle"] not in seen_angles:
            seen_angles.add(angle["angle"])
            unique_angles.append(angle)

    # Add a default angle if none were generated
    if not unique_angles:
        unique_angles.append({
            "angle": "job_search_strategy",
            "description": "General job search strategies and tips",
            "hook_type": "question",
            "tone": "inspirational",
            "why_now": "Evergreen topic with consistent interest",
        })

    return unique_angles[:5]


def get_signals_summary(signals: dict) -> str:
    """
    Generate a human-readable summary of the gathered signals.
    Useful for logging and debugging.
    """
    lines = [
        f"Research Signals Summary ({signals.get('timestamp', 'unknown')})",
        "=" * 50,
    ]

    # Sources status
    sources = []
    if signals.get("google_trends"):
        sources.append("Google Trends")
    if signals.get("reddit"):
        sources.append("Reddit")
    if signals.get("web_search"):
        sources.append("Tavily")
    lines.append(f"Sources: {', '.join(sources) if sources else 'None'}")

    # Top themes
    themes = signals.get("combined_themes", [])
    if themes:
        lines.append(f"\nTop Themes:")
        for t in themes[:5]:
            multi = " (multi-source)" if t.get("multi_source") else ""
            lines.append(f"  - {t['theme']}: score {t['score']}{multi}")

    # Recommended angles
    angles = signals.get("recommended_angles", [])
    if angles:
        lines.append(f"\nRecommended Angles:")
        for a in angles[:3]:
            lines.append(f"  - {a['angle']}: {a['description']}")

    # Errors
    errors = signals.get("errors", [])
    if errors:
        lines.append(f"\nErrors:")
        for e in errors:
            lines.append(f"  - {e['source']}: {e['error']}")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test the orchestrator
    import json
    logging.basicConfig(level=logging.INFO)

    print("Gathering signals from all sources...")
    signals = gather_all_signals()

    print("\n" + get_signals_summary(signals))

    print("\n\nFull data:")
    print(json.dumps(signals, indent=2, default=str))
