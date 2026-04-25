"""
Web search via Tavily API for real-time career/job news and trends.
Tavily provides AI-optimized search results perfect for content research.
Free tier: 1000 searches/month.
"""

import logging
from datetime import datetime
from typing import Optional

import requests

from config.settings import Config

logger = logging.getLogger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"

# Search queries for career/job content
DEFAULT_QUERIES = [
    "job market trends today",
    "hiring news this week",
    "career advice viral",
    "layoffs tech companies",
    "job search tips 2024",
    "referral hiring statistics",
]


def search_tavily(
    query: str,
    search_depth: str = "basic",
    max_results: int = 5,
    include_domains: list[str] = None,
    exclude_domains: list[str] = None,
) -> dict:
    """
    Search the web using Tavily API.

    Args:
        query: Search query string
        search_depth: "basic" (faster) or "advanced" (more thorough)
        max_results: Number of results to return (1-10)
        include_domains: Only include results from these domains
        exclude_domains: Exclude results from these domains

    Returns:
        Dict with search results and extracted content
    """
    if not Config.TAVILY_API_KEY:
        logger.info("Tavily API key not configured, using fallback data")
        return _get_fallback_search(query)

    try:
        payload = {
            "api_key": Config.TAVILY_API_KEY,
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": True,
            "include_raw_content": False,
        }

        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        response = requests.post(TAVILY_API_URL, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()

        return {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "answer": data.get("answer", ""),
            "results": [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", "")[:500],
                    "score": r.get("score", 0),
                }
                for r in data.get("results", [])
            ],
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Tavily API error: {e}")
        return _get_fallback_search(query)


def search_career_news() -> dict:
    """
    Run multiple career-related searches and aggregate results.
    Returns consolidated trending topics and news.
    """
    if not Config.TAVILY_API_KEY:
        logger.info("Tavily API key not configured, using fallback data")
        return _get_fallback_aggregated()

    results = {
        "timestamp": datetime.now().isoformat(),
        "searches": [],
        "top_stories": [],
        "key_insights": [],
    }

    # Priority queries for career content
    queries = [
        "job market news today",
        "hiring trends this week",
        "career advice going viral",
        "tech layoffs news",
    ]

    for query in queries:
        try:
            search_result = search_tavily(query, max_results=3)
            results["searches"].append({
                "query": query,
                "answer": search_result.get("answer", ""),
                "top_result": search_result["results"][0] if search_result.get("results") else None,
            })

            # Collect top stories
            for r in search_result.get("results", [])[:2]:
                if r.get("score", 0) > 0.5:
                    results["top_stories"].append({
                        "title": r["title"],
                        "url": r["url"],
                        "snippet": r["content"][:200],
                        "source_query": query,
                    })

        except Exception as e:
            logger.warning(f"Search failed for '{query}': {e}")
            continue

    # Deduplicate top stories by URL
    seen_urls = set()
    unique_stories = []
    for story in results["top_stories"]:
        if story["url"] not in seen_urls:
            seen_urls.add(story["url"])
            unique_stories.append(story)
    results["top_stories"] = unique_stories[:8]

    # Extract key insights from answers
    for search in results["searches"]:
        if search.get("answer"):
            results["key_insights"].append({
                "topic": search["query"],
                "insight": search["answer"][:300],
            })

    return results


def _get_fallback_search(query: str) -> dict:
    """Fallback data when Tavily API is unavailable."""
    return {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "fallback": True,
        "answer": "The job market continues to evolve with AI reshaping hiring practices. "
                  "Referrals remain the top method for landing jobs, with referred candidates "
                  "being 4x more likely to be hired.",
        "results": [
            {
                "title": "How AI is Transforming the Hiring Process in 2024",
                "url": "https://example.com/ai-hiring",
                "content": "Companies are increasingly using AI to screen resumes and conduct "
                          "initial interviews, making it more important than ever to optimize "
                          "your profile for automated systems.",
                "score": 0.85,
            },
            {
                "title": "The Power of Employee Referrals: Statistics That Matter",
                "url": "https://example.com/referral-stats",
                "content": "Studies show that referred candidates are hired 55% faster and stay "
                          "in their roles 70% longer than candidates from job boards.",
                "score": 0.82,
            },
        ],
    }


def _get_fallback_aggregated() -> dict:
    """Fallback aggregated data when Tavily API is unavailable."""
    return {
        "timestamp": datetime.now().isoformat(),
        "fallback": True,
        "searches": [
            {
                "query": "job market news today",
                "answer": "The job market shows mixed signals with tech seeing continued "
                         "restructuring while healthcare and AI roles grow.",
            },
            {
                "query": "hiring trends this week",
                "answer": "Companies are prioritizing skills-based hiring over degree requirements, "
                         "and remote/hybrid positions remain highly competitive.",
            },
        ],
        "top_stories": [
            {
                "title": "Companies Shift to Skills-Based Hiring",
                "url": "https://example.com/skills-hiring",
                "snippet": "Major employers are removing degree requirements and focusing on "
                          "demonstrated skills and potential.",
            },
            {
                "title": "Referrals Drive 40% of All Hires",
                "url": "https://example.com/referral-data",
                "snippet": "New data confirms that employee referrals continue to be the most "
                          "effective hiring channel for quality candidates.",
            },
        ],
        "key_insights": [
            {
                "topic": "job market",
                "insight": "The market favors candidates who leverage their network and "
                          "get warm introductions rather than cold applications.",
            },
            {
                "topic": "hiring trends",
                "insight": "AI screening tools are becoming standard, making profile "
                          "optimization crucial for job seekers.",
            },
        ],
    }


if __name__ == "__main__":
    # Test the module
    import json
    logging.basicConfig(level=logging.DEBUG)

    # Single search test
    result = search_tavily("job referral tips")
    print("Single search:")
    print(json.dumps(result, indent=2))

    # Aggregated search test
    print("\nAggregated search:")
    aggregated = search_career_news()
    print(json.dumps(aggregated, indent=2))
