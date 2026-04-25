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
        h["LinkedIn-Version"] = "202401"
        h["X-Restli-Protocol-Version"] = "2.0.0"
    return h


def _register_image_upload(owner_urn: str) -> tuple[str, str]:
    """
    Register an image upload with LinkedIn.
    Returns (upload_url, image_urn).
    """
    url = f"{RESTLI_BASE}/images?action=initializeUpload"
    payload = {
        "initializeUploadRequest": {
            "owner": owner_urn
        }
    }

    resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()["value"]

    return data["uploadUrl"], data["image"]


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
                           caption: str, is_org: bool = False) -> dict:
    """
    Create a multi-image (carousel) post on LinkedIn.
    """
    url = f"{RESTLI_BASE}/posts"

    # Build image array for carousel
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
    resp.raise_for_status()

    post_urn = resp.headers.get("x-restli-id", "unknown")
    return {"status": "published", "post_urn": post_urn}


def post_carousel(slide_paths: list[Path], caption: str,
                   post_to_personal: bool = True,
                   post_to_company: bool = True) -> dict:
    """
    Upload images and post a carousel to LinkedIn.

    Args:
        slide_paths: List of paths to slide PNG images
        caption: Post caption text
        post_to_personal: Post to personal profile
        post_to_company: Post to company page

    Returns:
        Dict with results for each target
    """
    if not Config.LINKEDIN_ACCESS_TOKEN:
        return {"error": "LinkedIn access token not configured"}

    results = {}

    targets = []
    if post_to_personal and Config.LINKEDIN_PERSON_URN:
        targets.append(("personal", Config.LINKEDIN_PERSON_URN, False))
    if post_to_company and Config.LINKEDIN_ORG_ID:
        org_urn = f"urn:li:organization:{Config.LINKEDIN_ORG_ID}"
        targets.append(("company", org_urn, True))

    for target_name, owner_urn, is_org in targets:
        try:
            print(f"  📤 Uploading {len(slide_paths)} images for {target_name}...")
            image_urns = []

            for path in slide_paths:
                upload_url, image_urn = _register_image_upload(owner_urn)
                _upload_image(upload_url, path)
                image_urns.append(image_urn)
                time.sleep(1)  # Rate limiting

            print(f"  📝 Creating carousel post on {target_name}...")
            result = _create_carousel_post(owner_urn, image_urns, caption, is_org)
            results[target_name] = result
            print(f"  ✅ Published to {target_name}!")

        except requests.exceptions.HTTPError as e:
            error_detail = e.response.text if e.response else str(e)
            results[target_name] = {"error": error_detail}
            print(f"  ❌ Failed to post to {target_name}: {error_detail}")

        except Exception as e:
            results[target_name] = {"error": str(e)}
            print(f"  ❌ Failed to post to {target_name}: {e}")

    return results


# =============================================
# OAuth Helper — run once to get access token
# =============================================

def generate_auth_url(client_id: str, redirect_uri: str = "http://localhost:8080/callback") -> str:
    """Generate the LinkedIn OAuth authorization URL."""
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


if __name__ == "__main__":
    print("LinkedIn OAuth Helper")
    print("=" * 40)
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
