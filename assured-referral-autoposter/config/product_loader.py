"""
Product configuration loader.
Loads product configs from JSON files and resolves credentials from environment.
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass


CONFIG_DIR = Path(__file__).parent
PRODUCTS_DIR = CONFIG_DIR / "products"


@dataclass
class ProductConfig:
    """Product configuration."""
    id: str
    name: str
    url: str
    tagline: str
    description: str
    niche: str
    tone: str
    accounts: dict

    def get_linkedin_credentials(self, account_id: str = "main") -> dict:
        """Get LinkedIn credentials for a specific account."""
        account = self._get_account("linkedin", account_id)
        if not account:
            return {}
        key = account["credentials_key"]
        return {
            "access_token": os.getenv(f"LINKEDIN_ACCESS_TOKEN_{key}", ""),
            "person_urn": os.getenv(f"LINKEDIN_PERSON_URN_{key}", ""),
        }

    def get_youtube_credentials(self, account_id: str = "main") -> dict:
        """Get YouTube credentials for a specific account."""
        account = self._get_account("youtube", account_id)
        if not account:
            return {}
        key = account["credentials_key"]
        return {
            "client_id": os.getenv(f"YOUTUBE_CLIENT_ID_{key}", ""),
            "client_secret": os.getenv(f"YOUTUBE_CLIENT_SECRET_{key}", ""),
            "refresh_token": os.getenv(f"YOUTUBE_REFRESH_TOKEN_{key}", ""),
            "channel_id": os.getenv(f"YOUTUBE_CHANNEL_ID_{key}", ""),
        }

    def get_instagram_credentials(self, account_id: str = "main") -> dict:
        """Get Instagram credentials for a specific account."""
        account = self._get_account("instagram", account_id)
        if not account:
            return {}
        key = account["credentials_key"]
        return {
            "access_token": os.getenv(f"INSTAGRAM_ACCESS_TOKEN_{key}", ""),
            "business_account_id": os.getenv(f"INSTAGRAM_BUSINESS_ACCOUNT_ID_{key}", ""),
            "facebook_page_id": os.getenv(f"FACEBOOK_PAGE_ID_{key}", ""),
        }

    def _get_account(self, platform: str, account_id: str) -> dict | None:
        """Get account config by platform and ID."""
        accounts = self.accounts.get(platform, [])
        for account in accounts:
            if account["id"] == account_id:
                return account
        return None


def load_product(product_id: str) -> ProductConfig:
    """Load a product configuration by ID."""
    config_path = PRODUCTS_DIR / f"{product_id}.json"

    if not config_path.exists():
        raise FileNotFoundError(f"Product config not found: {config_path}")

    with open(config_path) as f:
        data = json.load(f)

    return ProductConfig(
        id=data["id"],
        name=data["name"],
        url=data["url"],
        tagline=data["tagline"],
        description=data.get("description", ""),
        niche=data.get("niche", "business"),
        tone=data.get("tone", "professional"),
        accounts=data.get("accounts", {}),
    )


def list_products() -> list[str]:
    """List all available product IDs."""
    if not PRODUCTS_DIR.exists():
        return []
    return [p.stem for p in PRODUCTS_DIR.glob("*.json")]


def load_schedules() -> dict:
    """Load the schedules configuration."""
    schedules_path = CONFIG_DIR / "schedules.json"

    if not schedules_path.exists():
        return {}

    with open(schedules_path) as f:
        return json.load(f)
