"""
Central configuration loader for the AutoPoster pipeline.
Reads from .env (local) or environment variables (GitHub Actions).
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
    IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "azure")  # "azure", "stability", "gradient"
    STABILITY_API_KEY = os.getenv("STABILITY_API_KEY", "")

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

    # --- Brand ---
    BRAND_NAME = os.getenv("BRAND_NAME", "AssuredReferral")
    BRAND_URL = os.getenv("BRAND_URL", "https://assuredreferral.com")
    BRAND_TAGLINE = "Get Referred. Get Hired. Get Rewarded."

    # --- Content ---
    POSTING_TIME = os.getenv("POSTING_TIME", "10:00")
    CONTENT_NICHE = os.getenv("CONTENT_NICHE", "business_startup")
    TONE = os.getenv("TONE", "inspirational_bold")

    # --- Paths ---
    OUTPUT_DIR = PROJECT_ROOT / "output"
    SLIDES_DIR = OUTPUT_DIR / "slides"
    VIDEOS_DIR = OUTPUT_DIR / "videos"

    @classmethod
    def ensure_dirs(cls):
        cls.OUTPUT_DIR.mkdir(exist_ok=True)
        cls.SLIDES_DIR.mkdir(exist_ok=True)
        cls.VIDEOS_DIR.mkdir(exist_ok=True)

    @classmethod
    def validate(cls):
        """Check that critical keys are set."""
        issues = []
        if not cls.AZURE_OPENAI_API_KEY:
            issues.append("AZURE_OPENAI_API_KEY is missing")
        if not cls.AZURE_OPENAI_ENDPOINT:
            issues.append("AZURE_OPENAI_ENDPOINT is missing")
        if not cls.LINKEDIN_ACCESS_TOKEN:
            issues.append("LINKEDIN_ACCESS_TOKEN is missing (LinkedIn posting disabled)")
        if not cls.YOUTUBE_REFRESH_TOKEN:
            issues.append("YOUTUBE_REFRESH_TOKEN is missing (YouTube posting disabled)")
        return issues
