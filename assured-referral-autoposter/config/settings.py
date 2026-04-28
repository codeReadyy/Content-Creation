"""
Central configuration loader for the AutoPoster pipeline.
Reads from .env (local) or environment variables (GitHub Actions).

Supports both:
- Legacy mode: Single product using environment variables directly
- Multi-product mode: Load product config from JSON files
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root (ignored in GitHub Actions where env vars are set directly)
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    # --- Azure OpenAI ---
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
    AZURE_OPENAI_IMAGE_DEPLOYMENT = os.getenv("AZURE_OPENAI_IMAGE_DEPLOYMENT", "gpt-image-1-mini")

    # --- Image ---
    IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "stock")  # "stock", "azure", "stability", "gradient"
    STABILITY_API_KEY = os.getenv("STABILITY_API_KEY", "")
    UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")  # unsplash.com/developers, free 50 req/hr
    PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")  # pexels.com/api, free 200 req/month

    # --- LinkedIn ---
    LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    LINKEDIN_PERSON_URN = os.getenv("LINKEDIN_PERSON_URN", "")

    # --- YouTube ---
    YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
    YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "")
    YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")

    # --- Instagram ---
    INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "")
    INSTAGRAM_BUSINESS_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
    FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "")

    # --- Research Layer ---
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")  # tavily.com, free tier 1000/month
    REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")  # reddit.com/prefs/apps
    REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")

    # --- Brand ---
    BRAND_NAME = os.getenv("BRAND_NAME", "AssuredReferral")
    BRAND_URL = os.getenv("BRAND_URL", "https://assuredreferral.com")
    BRAND_TAGLINE = "Get Referred. Get Hired. Get Rewarded."

    # --- Telegram Notifications ---
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Content ---
    POSTING_TIME = os.getenv("POSTING_TIME", "10:00")
    CONTENT_NICHE = os.getenv("CONTENT_NICHE", "business_startup")
    TONE = os.getenv("TONE", "inspirational_bold")

    # --- Paths ---
    OUTPUT_DIR = PROJECT_ROOT / "output"
    SLIDES_DIR = OUTPUT_DIR / "slides"
    VIDEOS_DIR = OUTPUT_DIR / "videos"

    # Active product (set when running in multi-product mode)
    _active_product = None

    @classmethod
    def set_product(cls, product_id: str):
        """Set the active product and update paths accordingly."""
        from config.product_loader import load_product
        cls._active_product = load_product(product_id)

        # Update brand info from product config
        cls.BRAND_NAME = cls._active_product.name
        cls.BRAND_URL = cls._active_product.url
        cls.BRAND_TAGLINE = cls._active_product.tagline
        cls.CONTENT_NICHE = cls._active_product.niche
        cls.TONE = cls._active_product.tone

        # Update output directories to be product-specific
        cls.OUTPUT_DIR = PROJECT_ROOT / "output" / product_id
        cls.SLIDES_DIR = cls.OUTPUT_DIR / "slides"
        cls.VIDEOS_DIR = cls.OUTPUT_DIR / "videos"

    @classmethod
    def get_product(cls):
        """Get the active product config."""
        return cls._active_product

    @classmethod
    def ensure_dirs(cls):
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        cls.SLIDES_DIR.mkdir(exist_ok=True)
        cls.VIDEOS_DIR.mkdir(exist_ok=True)

    @classmethod
    def validate(cls, product_id: str = None):
        """Check that critical keys are set."""
        issues = []
        if not cls.AZURE_OPENAI_API_KEY:
            issues.append("AZURE_OPENAI_API_KEY is missing")
        if not cls.AZURE_OPENAI_ENDPOINT:
            issues.append("AZURE_OPENAI_ENDPOINT is missing")

        # If product specified, check product-specific credentials
        if product_id and cls._active_product:
            li_creds = cls._active_product.get_linkedin_credentials()
            if not li_creds.get("access_token"):
                issues.append(f"LINKEDIN_ACCESS_TOKEN_{cls._active_product.accounts.get('linkedin', [{}])[0].get('credentials_key', '')} is missing")
            yt_creds = cls._active_product.get_youtube_credentials()
            if not yt_creds.get("refresh_token"):
                issues.append(f"YOUTUBE_REFRESH_TOKEN_{cls._active_product.accounts.get('youtube', [{}])[0].get('credentials_key', '')} is missing")
        else:
            # Legacy mode - check default credentials
            if not cls.LINKEDIN_ACCESS_TOKEN:
                issues.append("LINKEDIN_ACCESS_TOKEN is missing (LinkedIn posting disabled)")
            if not cls.YOUTUBE_REFRESH_TOKEN:
                issues.append("YOUTUBE_REFRESH_TOKEN is missing (YouTube posting disabled)")

        return issues
