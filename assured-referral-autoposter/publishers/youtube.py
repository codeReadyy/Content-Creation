"""
YouTube publisher — uploads Shorts (vertical video from slides).
Uses YouTube Data API v3 with OAuth2.

Setup:
1. Go to https://console.cloud.google.com
2. Create a project → Enable "YouTube Data API v3"
3. Create OAuth 2.0 credentials (Desktop app type)
4. Run the auth helper below to get a refresh token
5. Add credentials to .env
"""

import json
import requests
from pathlib import Path
from config.settings import Config


YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _get_credentials(account_id: str = "main") -> dict:
    """Get YouTube credentials for the specified account."""
    product = Config.get_product()

    if product:
        return product.get_youtube_credentials(account_id)

    # Legacy mode - use direct config
    return {
        "client_id": Config.YOUTUBE_CLIENT_ID,
        "client_secret": Config.YOUTUBE_CLIENT_SECRET,
        "refresh_token": Config.YOUTUBE_REFRESH_TOKEN,
        "channel_id": Config.YOUTUBE_CHANNEL_ID,
    }


def _get_fresh_access_token(creds: dict = None) -> str:
    """Exchange refresh token for a fresh access token."""
    if creds is None:
        creds = _get_credentials()

    data = {
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token"
    }

    resp = requests.post(YOUTUBE_TOKEN_URL, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def upload_short(video_path: Path, title: str, description: str,
                  tags: list[str] = None, account_id: str = "main") -> dict:
    """
    Upload a video as a YouTube Short.

    Args:
        video_path: Path to MP4 video file
        title: Video title (max 100 chars)
        description: Video description
        tags: List of tags
        account_id: Account ID to use (for multi-account support)

    Returns:
        Dict with video ID and status
    """
    creds = _get_credentials(account_id)

    if not creds.get("refresh_token"):
        return {"error": "YouTube credentials not configured"}

    try:
        access_token = _get_fresh_access_token(creds)
    except Exception as e:
        return {"error": f"Failed to get YouTube access token: {e}"}

    # Video metadata
    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags or ["career", "jobs", "referral", "hiring"],
            "categoryId": "22",  # People & Blogs
            "defaultLanguage": "en"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "shorts": {
                "pendingDeclaration": True  # Mark as Short
            }
        }
    }

    # Resumable upload
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4",
        "X-Upload-Content-Length": str(video_path.stat().st_size)
    }

    # Step 1: Initialize upload
    init_url = f"{YOUTUBE_UPLOAD_URL}?uploadType=resumable&part=snippet,status"
    resp = requests.post(init_url, headers=headers, json=metadata, timeout=30)
    resp.raise_for_status()
    upload_url = resp.headers["Location"]

    # Step 2: Upload the video file
    with open(video_path, "rb") as f:
        upload_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "video/mp4"
        }
        resp = requests.put(upload_url, headers=upload_headers, data=f, timeout=300)
        resp.raise_for_status()

    result = resp.json()
    video_id = result.get("id", "unknown")

    print(f"  ✅ YouTube Short uploaded: https://youtube.com/shorts/{video_id}")
    return {
        "status": "uploaded",
        "video_id": video_id,
        "url": f"https://youtube.com/shorts/{video_id}"
    }


# =============================================
# OAuth Helper — run once to get refresh token
# =============================================

def generate_auth_url(client_id: str,
                       redirect_uri: str = "http://localhost:8080") -> str:
    """Generate the Google OAuth authorization URL."""
    scopes = "https://www.googleapis.com/auth/youtube.upload"
    return (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&redirect_uri={redirect_uri}"
        f"&response_type=code&scope={scopes}"
        f"&access_type=offline&prompt=consent"
    )


def exchange_code_for_tokens(code: str, client_id: str, client_secret: str,
                              redirect_uri: str = "http://localhost:8080") -> dict:
    """Exchange authorization code for access + refresh tokens."""
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    resp = requests.post(YOUTUBE_TOKEN_URL, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    print("YouTube OAuth Helper")
    print("=" * 40)
    client_id = input("Enter your Google OAuth Client ID: ")
    auth_url = generate_auth_url(client_id)
    print(f"\n1. Open this URL in your browser:\n{auth_url}")
    print("\n2. Authorize the app and copy the 'code' from the redirect URL")
    code = input("\n3. Paste the authorization code here: ")
    client_secret = input("4. Enter your Client Secret: ")

    tokens = exchange_code_for_tokens(code, client_id, client_secret)
    print(f"\n✅ Access Token: {tokens['access_token'][:20]}...")
    print(f"   Refresh Token: {tokens.get('refresh_token', 'N/A')}")
    print(f"\nAdd YOUTUBE_REFRESH_TOKEN to your .env file")
