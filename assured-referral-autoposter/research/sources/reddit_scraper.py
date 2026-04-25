"""
Reddit scraper for career/job-related subreddits.
Fetches hot posts from r/jobs, r/cscareerquestions, r/recruitinghell, r/jobsearchhacks.
Uses PRAW (Python Reddit API Wrapper) for authenticated access.
"""

import logging
from datetime import datetime
from typing import Optional

from config.settings import Config

logger = logging.getLogger(__name__)

# Target subreddits for career/job content
CAREER_SUBREDDITS = [
    "jobs",
    "cscareerquestions",
    "recruitinghell",
    "jobsearchhacks",
    "careerguidance",
    "resumes",
    "interviews",
    "layoffs",
]

# Keywords that indicate high-engagement career discussions
ENGAGEMENT_KEYWORDS = [
    "referral",
    "hired",
    "offer",
    "interview",
    "rejected",
    "layoff",
    "salary",
    "negotiate",
    "remote",
    "hybrid",
    "linkedin",
    "recruiter",
    "ats",
    "resume",
    "networking",
    "job search",
    "career change",
    "promotion",
]


def get_reddit_hot_posts(
    subreddits: list[str] = None,
    posts_per_sub: int = 10,
    min_score: int = 50,
) -> dict:
    """
    Fetch hot posts from career-related subreddits.

    Args:
        subreddits: List of subreddit names (without r/)
        posts_per_sub: Number of posts to fetch per subreddit
        min_score: Minimum upvote score to include

    Returns:
        Dict with trending posts, top discussions, and extracted themes
    """
    subreddits = subreddits or CAREER_SUBREDDITS[:4]

    # Check if Reddit credentials are configured
    if not Config.REDDIT_CLIENT_ID or not Config.REDDIT_CLIENT_SECRET:
        logger.info("Reddit credentials not configured, using fallback data")
        return _get_fallback_reddit()

    try:
        import praw
    except ImportError:
        logger.warning("praw not installed. Run: pip install praw")
        return _get_fallback_reddit()

    try:
        reddit = praw.Reddit(
            client_id=Config.REDDIT_CLIENT_ID,
            client_secret=Config.REDDIT_CLIENT_SECRET,
            user_agent="AssuredReferral-Research/1.0",
        )

        results = {
            "timestamp": datetime.now().isoformat(),
            "subreddits_checked": subreddits,
            "hot_posts": [],
            "rising_posts": [],
            "top_themes": [],
            "sentiment_signals": [],
        }

        all_posts = []

        for sub_name in subreddits:
            try:
                subreddit = reddit.subreddit(sub_name)

                # Get hot posts
                for post in subreddit.hot(limit=posts_per_sub):
                    if post.score >= min_score and not post.stickied:
                        post_data = {
                            "subreddit": sub_name,
                            "title": post.title,
                            "score": post.score,
                            "num_comments": post.num_comments,
                            "url": f"https://reddit.com{post.permalink}",
                            "created_utc": datetime.fromtimestamp(post.created_utc).isoformat(),
                            "flair": post.link_flair_text,
                            "is_self": post.is_self,
                        }

                        # Extract selftext snippet for context
                        if post.is_self and post.selftext:
                            post_data["snippet"] = post.selftext[:300].replace("\n", " ")

                        all_posts.append(post_data)

                # Get rising posts (early trending signals)
                for post in subreddit.rising(limit=5):
                    if post.score >= 10:
                        results["rising_posts"].append({
                            "subreddit": sub_name,
                            "title": post.title,
                            "score": post.score,
                            "age_hours": (datetime.now().timestamp() - post.created_utc) / 3600,
                        })

            except Exception as e:
                logger.warning(f"Failed to fetch r/{sub_name}: {e}")
                continue

        # Sort by engagement (score + comments)
        all_posts.sort(key=lambda x: x["score"] + x["num_comments"] * 2, reverse=True)
        results["hot_posts"] = all_posts[:15]

        # Extract themes from titles
        results["top_themes"] = _extract_themes(all_posts)

        # Detect sentiment signals
        results["sentiment_signals"] = _detect_sentiment(all_posts)

        return results

    except Exception as e:
        logger.error(f"Reddit API error: {e}")
        return _get_fallback_reddit()


def _extract_themes(posts: list[dict]) -> list[dict]:
    """Extract recurring themes from post titles."""
    theme_counts = {}

    for post in posts:
        title_lower = post["title"].lower()
        for keyword in ENGAGEMENT_KEYWORDS:
            if keyword in title_lower:
                theme_counts[keyword] = theme_counts.get(keyword, 0) + 1

    # Sort by frequency
    sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)

    return [
        {"theme": theme, "mentions": count, "relevance": "high" if count >= 3 else "medium"}
        for theme, count in sorted_themes[:8]
    ]


def _detect_sentiment(posts: list[dict]) -> list[dict]:
    """
    Detect sentiment signals from post titles and engagement.
    Looks for patterns indicating frustration, success, or advice-seeking.
    """
    signals = []

    frustration_words = ["rejected", "ghosted", "layoff", "fired", "frustrat", "rant", "vent"]
    success_words = ["hired", "offer", "accepted", "got the job", "finally", "success"]
    advice_words = ["how to", "tips", "advice", "help", "should i", "is it worth"]

    frustration_count = 0
    success_count = 0
    advice_count = 0

    for post in posts:
        title_lower = post["title"].lower()
        if any(word in title_lower for word in frustration_words):
            frustration_count += 1
        if any(word in title_lower for word in success_words):
            success_count += 1
        if any(word in title_lower for word in advice_words):
            advice_count += 1

    total = len(posts) or 1

    if frustration_count / total > 0.3:
        signals.append({
            "signal": "high_frustration",
            "description": "Many job seekers expressing frustration with the market",
            "content_angle": "empathy + solutions",
        })

    if success_count / total > 0.2:
        signals.append({
            "signal": "success_stories_trending",
            "description": "Success stories getting high engagement",
            "content_angle": "celebration + how-they-did-it",
        })

    if advice_count / total > 0.25:
        signals.append({
            "signal": "advice_seeking",
            "description": "High demand for actionable career advice",
            "content_angle": "tactical tips + frameworks",
        })

    return signals


def _get_fallback_reddit() -> dict:
    """
    Fallback Reddit data when API is unavailable.
    Based on evergreen career discussion patterns.
    """
    return {
        "timestamp": datetime.now().isoformat(),
        "fallback": True,
        "subreddits_checked": CAREER_SUBREDDITS[:4],
        "hot_posts": [
            {
                "subreddit": "jobs",
                "title": "Finally got an offer after 8 months of searching - here's what worked",
                "score": 2500,
                "num_comments": 340,
                "flair": "Success Story",
            },
            {
                "subreddit": "cscareerquestions",
                "title": "Is the job market actually getting better or am I just lucky?",
                "score": 1800,
                "num_comments": 520,
                "flair": "Discussion",
            },
            {
                "subreddit": "recruitinghell",
                "title": "Recruiter ghosted me after 5 rounds of interviews",
                "score": 3200,
                "num_comments": 450,
                "flair": "Rant",
            },
            {
                "subreddit": "jobsearchhacks",
                "title": "The hidden job market is real - how I got 3 interviews through referrals",
                "score": 890,
                "num_comments": 120,
                "flair": "Tips",
            },
        ],
        "top_themes": [
            {"theme": "referral", "mentions": 5, "relevance": "high"},
            {"theme": "interview", "mentions": 8, "relevance": "high"},
            {"theme": "rejected", "mentions": 4, "relevance": "high"},
            {"theme": "salary", "mentions": 3, "relevance": "medium"},
            {"theme": "remote", "mentions": 3, "relevance": "medium"},
        ],
        "sentiment_signals": [
            {
                "signal": "advice_seeking",
                "description": "High demand for actionable career advice",
                "content_angle": "tactical tips + frameworks",
            },
        ],
        "rising_posts": [
            {
                "subreddit": "jobs",
                "title": "Unpopular opinion: networking > applying online",
                "score": 45,
                "age_hours": 3.5,
            },
        ],
    }


if __name__ == "__main__":
    # Test the module
    import json
    logging.basicConfig(level=logging.DEBUG)
    reddit_data = get_reddit_hot_posts()
    print(json.dumps(reddit_data, indent=2))
