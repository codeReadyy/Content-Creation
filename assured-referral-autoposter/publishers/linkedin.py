"""
LinkedIn publisher — posts carousel images to personal profile and company page.
Uses LinkedIn's 3-legged OAuth and the Posts API (v2).

Setup:
1. Go to https://www.linkedin.com/developers/apps
2. Create an app → Request access to "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect"
3. Under Products, add "Share on LinkedIn"
4. Get your 3-legged OAuth access token using the auth helper script
5. Find your Person URN: GET https://api.linkedin.com/v2/userinfo → sub field
"""

import json
import time
import requests
from pathlib import Path
from config.settings import Config


API_BASE = "https://api.linkedin.com/v2"
RESTLI_BASE = "https://api.linkedin.com/rest"


def _headers(restli: bool = True) -> dict:
    h = {
        "Authorization": f"Bearer {Config.LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    if restli:
        # LinkedIn API version - use stable version
        # See: https://learn.microsoft.com/en-us/linkedin/marketing/versioning
        h["LinkedIn-Version"] = "202401"
        h["X-Restli-Protocol-Version"] = "2.0.0"
    return h


def _check_api_version() -> str:
    """Try to find a working API version."""
    versions = ["202401", "202312", "202306", "202301"]

    for version in versions:
        headers = {
            "Authorization": f"Bearer {Config.LINKEDIN_ACCESS_TOKEN}",
            "Content-Type": "application/json",
            "LinkedIn-Version": version,
            "X-Restli-Protocol-Version": "2.0.0"
        }
        try:
            resp = requests.post(
                f"{RESTLI_BASE}/images?action=initializeUpload",
                headers=headers,
                json={"initializeUploadRequest": {"owner": Config.LINKEDIN_PERSON_URN}},
                timeout=10
            )
            if resp.status_code != 426:
                return version
        except:
            pass
    return "202401"


def _register_image_upload(owner_urn: str) -> tuple[str, str]:
    """
    Register an image upload with LinkedIn.
    Returns (upload_url, image_urn).

    Tries REST API first, falls back to legacy v2 API if needed.
    """
    # Try REST API (newer)
    rest_url = f"{RESTLI_BASE}/images?action=initializeUpload"
    rest_payload = {
        "initializeUploadRequest": {
            "owner": owner_urn
        }
    }

    resp = requests.post(rest_url, headers=_headers(), json=rest_payload, timeout=30)

    # If REST API fails with 426, try legacy v2 API
    if resp.status_code == 426:
        print("  ℹ️  REST API unavailable, trying legacy API...")
        return _register_image_upload_legacy(owner_urn)

    resp.raise_for_status()
    data = resp.json()["value"]
    return data["uploadUrl"], data["image"]


def _register_image_upload_legacy(owner_urn: str) -> tuple[str, str]:
    """
    Legacy v2 API for image upload registration.
    Used when REST API returns 426.
    """
    url = f"{API_BASE}/assets?action=registerUpload"

    payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": owner_urn,
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent"
                }
            ]
        }
    }

    headers = {
        "Authorization": f"Bearer {Config.LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()

    data = resp.json()["value"]
    upload_url = data["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn = data["asset"]

    return upload_url, asset_urn


def _upload_image(upload_url: str, image_path: Path) -> None:
    """Upload the actual image bytes to LinkedIn's upload URL."""
    headers = {
        "Authorization": f"Bearer {Config.LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/octet-stream",
    }

    with open(image_path, "rb") as f:
        resp = requests.put(upload_url, headers=headers, data=f.read(), timeout=60)
        resp.raise_for_status()


def _create_carousel_post(owner_urn: str, image_urns: list[str],
                           caption: str) -> dict:
    """
    Create a multi-image (carousel) post on LinkedIn.
    Tries REST API first, falls back to UGC API if needed.
    """
    # Try REST API first
    url = f"{RESTLI_BASE}/posts"

    images = []
    for i, urn in enumerate(image_urns):
        images.append({
            "id": urn,
            "altText": f"Slide {i + 1}"
        })

    post_body = {
        "author": owner_urn,
        "commentary": caption,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        },
        "content": {
            "multiImage": {
                "images": images
            }
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False
    }

    resp = requests.post(url, headers=_headers(), json=post_body, timeout=30)

    # If REST API fails with 426, try legacy UGC API
    if resp.status_code == 426:
        print("  ℹ️  REST Posts API unavailable, trying UGC API...")
        return _create_ugc_post(owner_urn, image_urns, caption)

    resp.raise_for_status()

    post_urn = resp.headers.get("x-restli-id", "unknown")
    return {"status": "published", "post_urn": post_urn}


def _create_ugc_post(owner_urn: str, image_urns: list[str], caption: str) -> dict:
    """
    Create post using legacy UGC (User Generated Content) API.
    """
    url = f"{API_BASE}/ugcPosts"

    # Build media array
    media = []
    for i, urn in enumerate(image_urns):
        media.append({
            "status": "READY",
            "media": urn,
            "title": {
                "text": f"Slide {i + 1}"
            }
        })

    post_body = {
        "author": owner_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {
                    "text": caption
                },
                "shareMediaCategory": "IMAGE",
                "media": media
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

    headers = {
        "Authorization": f"Bearer {Config.LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0"
    }

    resp = requests.post(url, headers=headers, json=post_body, timeout=30)
    resp.raise_for_status()

    post_id = resp.json().get("id", "unknown")
    return {"status": "published", "post_urn": post_id}


def post_carousel(slide_paths: list[Path], caption: str) -> dict:
    """
    Upload images and post a carousel to the personal LinkedIn profile.

    Args:
        slide_paths: List of paths to slide PNG images
        caption: Post caption text

    Returns:
        Dict with result
    """
    if not Config.LINKEDIN_ACCESS_TOKEN:
        return {"error": "LinkedIn access token not configured"}
    if not Config.LINKEDIN_PERSON_URN:
        return {"error": "LINKEDIN_PERSON_URN not configured"}

    try:
        print(f"  📤 Uploading {len(slide_paths)} images...")
        image_urns = []

        for path in slide_paths:
            upload_url, image_urn = _register_image_upload(Config.LINKEDIN_PERSON_URN)
            _upload_image(upload_url, path)
            image_urns.append(image_urn)
            time.sleep(1)  # Rate limiting

        print("  📝 Creating carousel post...")
        result = _create_carousel_post(Config.LINKEDIN_PERSON_URN, image_urns, caption)
        print("  ✅ Published to LinkedIn!")
        return result

    except requests.exceptions.HTTPError as e:
        error_detail = e.response.text if e.response else str(e)
        print(f"  ❌ Failed to post to LinkedIn: {error_detail}")
        return {"error": error_detail}

    except Exception as e:
        print(f"  ❌ Failed to post to LinkedIn: {e}")
        return {"error": str(e)}


# =============================================
# OAuth Helper — run once to get access token
# =============================================

def generate_auth_url(client_id: str, redirect_uri: str = "http://localhost:8080/callback") -> str:
    """Generate the LinkedIn OAuth authorization URL."""
    # w_member_social — post on behalf of the signed-in member
    # openid + profile  — needed to get person URN via /v2/userinfo
    scopes = "openid%20profile%20w_member_social"
    return (
        f"https://www.linkedin.com/oauth/v2/authorization?"
        f"response_type=code&client_id={client_id}&redirect_uri={redirect_uri}"
        f"&scope={scopes}"
    )


def exchange_code_for_token(code: str, client_id: str, client_secret: str,
                             redirect_uri: str = "http://localhost:8080/callback") -> dict:
    """Exchange the authorization code for an access token."""
    url = "https://www.linkedin.com/oauth/v2/accessToken"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret
    }
    resp = requests.post(url, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def test_linkedin_credentials() -> dict:
    """
    Test LinkedIn credentials by checking token validity and person URN.
    Run: cd assured-referral-autoposter && PYTHONPATH=. python publishers/linkedin.py test
    """
    print("Testing LinkedIn Credentials...")
    print("=" * 50)

    if not Config.LINKEDIN_ACCESS_TOKEN:
        print("❌ LINKEDIN_ACCESS_TOKEN not set in .env")
        return {"error": "No access token"}

    if not Config.LINKEDIN_PERSON_URN:
        print("❌ LINKEDIN_PERSON_URN not set in .env")
        return {"error": "No person URN"}

    print(f"✓ Access Token: {Config.LINKEDIN_ACCESS_TOKEN[:20]}...")
    print(f"✓ Person URN: {Config.LINKEDIN_PERSON_URN}")

    # Test 1: Check if token is valid by getting user info
    print("\n1. Testing token validity...")
    try:
        resp = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {Config.LINKEDIN_ACCESS_TOKEN}"},
            timeout=10
        )
        if resp.status_code == 200:
            user_info = resp.json()
            print(f"   ✅ Token valid! User: {user_info.get('name', 'Unknown')}")
            print(f"   ℹ️  Your person ID (sub): {user_info.get('sub')}")
            expected_urn = f"urn:li:person:{user_info.get('sub')}"
            if Config.LINKEDIN_PERSON_URN != expected_urn:
                print(f"   ⚠️  URN mismatch!")
                print(f"      Current:  {Config.LINKEDIN_PERSON_URN}")
                print(f"      Expected: {expected_urn}")
        else:
            print(f"   ❌ Token invalid: {resp.status_code} - {resp.text}")
            return {"error": f"Token invalid: {resp.status_code}"}
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return {"error": str(e)}

    # Test 2: Try REST API for image upload
    print("\n2. Testing REST API (images)...")
    rest_works = False
    try:
        resp = requests.post(
            f"{RESTLI_BASE}/images?action=initializeUpload",
            headers=_headers(),
            json={"initializeUploadRequest": {"owner": Config.LINKEDIN_PERSON_URN}},
            timeout=10
        )
        if resp.status_code == 200:
            print("   ✅ REST API works!")
            rest_works = True
        elif resp.status_code == 426:
            print("   ⚠️  REST API returned 426 (Upgrade Required)")
            print("      This usually means your app needs different products.")
            print("      Trying legacy API...")
        else:
            print(f"   ⚠️  REST API: {resp.status_code} - {resp.text[:100]}")
    except Exception as e:
        print(f"   ⚠️  REST API error: {e}")

    # Test 3: Try legacy v2 API
    if not rest_works:
        print("\n3. Testing Legacy v2 API (assets)...")
        try:
            resp = requests.post(
                f"{API_BASE}/assets?action=registerUpload",
                headers={
                    "Authorization": f"Bearer {Config.LINKEDIN_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "registerUploadRequest": {
                        "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                        "owner": Config.LINKEDIN_PERSON_URN,
                        "serviceRelationships": [{
                            "relationshipType": "OWNER",
                            "identifier": "urn:li:userGeneratedContent"
                        }]
                    }
                },
                timeout=10
            )
            if resp.status_code == 200:
                print("   ✅ Legacy API works! Pipeline will use this.")
                return {"status": "success", "api": "legacy"}
            else:
                print(f"   ❌ Legacy API failed: {resp.status_code}")
                print(f"      Response: {resp.text[:200]}")
        except Exception as e:
            print(f"   ❌ Legacy API error: {e}")

        print("\n" + "=" * 50)
        print("TROUBLESHOOTING:")
        print("=" * 50)
        print("1. Go to: https://www.linkedin.com/developers/apps")
        print("2. Select your app")
        print("3. Go to 'Products' tab")
        print("4. Ensure these are added:")
        print("   - 'Share on LinkedIn'")
        print("   - 'Sign In with LinkedIn using OpenID Connect'")
        print("5. After adding products, generate a NEW access token")
        print("=" * 50)
        return {"error": "Both APIs failed"}

    return {"status": "success", "api": "rest"}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Run: python publishers/linkedin.py test
        test_linkedin_credentials()
    else:
        print("LinkedIn OAuth Helper")
        print("=" * 40)
        print("\nOptions:")
        print("  python publishers/linkedin.py test  - Test your credentials")
        print("  python publishers/linkedin.py       - Generate new token")
        print()

        choice = input("Generate new token? (y/n): ").lower()
        if choice != 'y':
            sys.exit(0)

        client_id = input("Enter your LinkedIn App Client ID: ")
        auth_url = generate_auth_url(client_id)
        print(f"\n1. Open this URL in your browser:\n{auth_url}")
        print("\n2. Authorize the app and copy the 'code' from the redirect URL")
        code = input("\n3. Paste the authorization code here: ")
        client_secret = input("4. Enter your Client Secret: ")

        token_data = exchange_code_for_token(code, client_id, client_secret)
        print(f"\n✅ Access Token: {token_data['access_token']}")
        print(f"   Expires in: {token_data.get('expires_in', 'unknown')} seconds")
        print(f"\nAdd this to your .env file as LINKEDIN_ACCESS_TOKEN")
