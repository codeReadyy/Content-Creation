"""
Google Trends scraper for job/hiring/career keywords.
Uses pytrends to fetch trending search queries in the employment space.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Job/career related seed keywords to track
SEED_KEYWORDS = [
    "job search",
    "hiring",
    "layoffs",
    "job interview",
    "resume tips",
    "career change",
    "remote work",
    "salary negotiation",
    "job referral",
    "tech jobs",
]

# Related topics to expand search
CAREER_TOPICS = [
    "job market",
    "unemployment",
    "linkedin",
    "recruiting",
    "work from home",
]


def get_google_trends(
    keywords: list[str] = None,
    timeframe: str = "now 7-d",
    geo: str = "US",
) -> dict:
    """
    Fetch Google Trends data for job/career related keywords.

    Args:
        keywords: List of keywords to track (defaults to SEED_KEYWORDS)
        timeframe: Trends timeframe ('now 1-d', 'now 7-d', 'today 1-m', etc.)
        geo: Geographic region code

    Returns:
        Dict with trending keywords, rising queries, and related topics
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("pytrends not installed. Run: pip install pytrends")
        return _get_fallback_trends()

    keywords = keywords or SEED_KEYWORDS[:5]  # pytrends limit is 5 keywords

    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 25))

        # Build payload
        pytrends.build_payload(keywords, cat=0, timeframe=timeframe, geo=geo)

        results = {
            "timestamp": datetime.now().isoformat(),
            "keywords_tracked": keywords,
            "interest_over_time": [],
            "rising_queries": [],
            "related_topics": [],
            "top_queries": [],
        }

        # Get interest over time
        try:
            interest_df = pytrends.interest_over_time()
            if not interest_df.empty:
                # Get the most recent data point for each keyword
                latest = interest_df.iloc[-1].to_dict()
                latest.pop("isPartial", None)
                results["interest_over_time"] = [
                    {"keyword": k, "interest": v}
                    for k, v in sorted(latest.items(), key=lambda x: x[1], reverse=True)
                ]
        except Exception as e:
            logger.debug(f"Interest over time failed: {e}")

        # Get related queries for each keyword
        try:
            related_queries = pytrends.related_queries()
            for keyword in keywords:
                if keyword in related_queries and related_queries[keyword]["rising"] is not None:
                    rising = related_queries[keyword]["rising"]
                    if not rising.empty:
                        for _, row in rising.head(5).iterrows():
                            results["rising_queries"].append({
                                "keyword": keyword,
                                "query": row["query"],
                                "value": str(row["value"]),
                            })

                if keyword in related_queries and related_queries[keyword]["top"] is not None:
                    top = related_queries[keyword]["top"]
                    if not top.empty:
                        for _, row in top.head(3).iterrows():
                            results["top_queries"].append({
                                "keyword": keyword,
                                "query": row["query"],
                                "value": int(row["value"]),
                            })
        except Exception as e:
            logger.debug(f"Related queries failed: {e}")

        # Get related topics
        try:
            related_topics = pytrends.related_topics()
            for keyword in keywords:
                if keyword in related_topics and related_topics[keyword]["rising"] is not None:
                    rising = related_topics[keyword]["rising"]
                    if not rising.empty:
                        for _, row in rising.head(3).iterrows():
                            results["related_topics"].append({
                                "keyword": keyword,
                                "topic": row.get("topic_title", str(row.get("topic_mid", ""))),
                                "value": str(row.get("value", "")),
                            })
        except Exception as e:
            logger.debug(f"Related topics failed: {e}")

        # Get trending searches (real-time)
        try:
            trending = pytrends.trending_searches(pn="united_states")
            career_related = []
            career_terms = {"job", "hire", "layoff", "work", "career", "salary", "company", "ceo", "tech"}
            for query in trending[0].tolist()[:20]:
                query_lower = query.lower()
                if any(term in query_lower for term in career_terms):
                    career_related.append(query)
            if career_related:
                results["realtime_trending"] = career_related[:5]
        except Exception as e:
            logger.debug(f"Trending searches failed: {e}")

        return results

    except Exception as e:
        logger.error(f"Google Trends API error: {e}")
        return _get_fallback_trends()


def _get_fallback_trends() -> dict:
    """
    Fallback trending data when pytrends fails or is unavailable.
    Returns evergreen career topics that are always relevant.
    """
    return {
        "timestamp": datetime.now().isoformat(),
        "fallback": True,
        "keywords_tracked": SEED_KEYWORDS[:5],
        "rising_queries": [
            {"keyword": "job search", "query": "how to get a job referral", "value": "Breakout"},
            {"keyword": "job search", "query": "hidden job market", "value": "+500%"},
            {"keyword": "hiring", "query": "AI hiring tools", "value": "+350%"},
            {"keyword": "resume tips", "query": "ATS friendly resume", "value": "+200%"},
            {"keyword": "career change", "query": "career pivot 2024", "value": "+180%"},
        ],
        "related_topics": [
            {"keyword": "job search", "topic": "Employee referral", "value": "Breakout"},
            {"keyword": "hiring", "topic": "Artificial intelligence", "value": "+400%"},
            {"keyword": "remote work", "topic": "Hybrid work", "value": "+250%"},
        ],
        "top_queries": [
            {"keyword": "job search", "query": "linkedin job search", "value": 100},
            {"keyword": "job search", "query": "indeed jobs", "value": 85},
            {"keyword": "job interview", "query": "interview tips", "value": 90},
        ],
    }


if __name__ == "__main__":
    # Test the module
    import json
    logging.basicConfig(level=logging.DEBUG)
    trends = get_google_trends()
    print(json.dumps(trends, indent=2))
