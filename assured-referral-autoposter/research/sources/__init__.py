"""
Research data sources for trending content signals.
"""

from research.sources.google_trends import get_google_trends
from research.sources.reddit_scraper import get_reddit_hot_posts
from research.sources.web_search import search_tavily

__all__ = ["get_google_trends", "get_reddit_hot_posts", "search_tavily"]
