"""
Instagram publisher — PLACEHOLDER.
Posts carousel images via Instagram Graph API.

Prerequisites (not yet set up):
1. Facebook Business Page linked to Instagram Professional account
2. Meta App with instagram_content_publish permission
3. Long-lived access token

Setup guide: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/content-publishing

This module is a placeholder — fill in credentials when ready.
"""

import time
import requests
from pathlib import Path
from config.settings import Config


GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


def _upload_image_to_container(image_url: str, caption: str = None,
                                 is_carousel_item: bool = True) -> str:
    """Create a media container for a single image."""
    url = f"{GRAPH_API_BASE}/{Config.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media"

    params = {
        "image_url": image_url,
        "access_token": Config.INSTAGRAM_ACCESS_TOKEN,
        "is_carousel_item": is_carousel_item,
    }
    if caption and not is_carousel_item:
        params["caption"] = caption

    resp = requests.post(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def _create_carousel_container(children_ids: list[str], caption: str) -> str:
    """Create a carousel container from individual image containers."""
    url = f"{GRAPH_API_BASE}/{Config.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media"

    params = {
        "media_type": "CAROUSEL",
        "children": ",".join(children_ids),
        "caption": caption,
        "access_token": Config.INSTAGRAM_ACCESS_TOKEN,
    }

    resp = requests.post(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def _publish_container(container_id: str) -> dict:
    """Publish a media container."""
    url = f"{GRAPH_API_BASE}/{Config.INSTAGRAM_BUSINESS_ACCOUNT_ID}/media_publish"

    params = {
        "creation_id": container_id,
        "access_token": Config.INSTAGRAM_ACCESS_TOKEN,
    }

    resp = requests.post(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def post_carousel(image_urls: list[str], caption: str) -> dict:
    """
    Post a carousel to Instagram.

    IMPORTANT: Instagram requires publicly accessible image URLs.
    You'll need to host the images (e.g., on S3, Cloudinary, or a CDN)
    before calling this function.

    Args:
        image_urls: List of public URLs to the slide images
        caption: Post caption with hashtags

    Returns:
        Dict with post ID and status
    """
    if not Config.INSTAGRAM_ACCESS_TOKEN:
        return {
            "status": "skipped",
            "reason": "Instagram not configured yet. "
                      "Set up a Professional account and add credentials to .env"
        }

    try:
        # Step 1: Create containers for each image
        children_ids = []
        for i, url in enumerate(image_urls):
            container_id = _upload_image_to_container(url)
            children_ids.append(container_id)
            print(f"  📤 Uploaded image {i + 1} to Instagram container")
            time.sleep(2)  # Rate limiting

        # Step 2: Create carousel container
        carousel_id = _create_carousel_container(children_ids, caption)
        print(f"  🎠 Carousel container created")

        # Step 3: Wait for processing, then publish
        time.sleep(5)  # Instagram needs time to process
        result = _publish_container(carousel_id)

        print(f"  ✅ Published to Instagram!")
        return {"status": "published", "post_id": result.get("id")}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# Note: For Instagram, images must be hosted at public URLs.
# You'll need a simple image hosting step. Options:
# 1. Upload to S3/Cloudinary in the pipeline
# 2. Use a free image hosting API
# 3. Host a simple Flask server that serves the images temporarily
