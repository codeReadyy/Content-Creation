#!/usr/bin/env python3
"""
LinkedIn OAuth Token Generator
================================
Run this ONCE whenever your LinkedIn token expires (every ~60 days).

Usage:
    .venv/bin/python get_linkedin_token.py

What it does:
1. Starts a temporary local server on port 8080
2. Prints the LinkedIn authorization URL — open it in your browser
3. After you authorize, captures the code automatically
4. Exchanges the code for an access token
5. Prints the token + your Person URN (needed for config)

Then update:
  - Your .env file (for local runs): LINKEDIN_ACCESS_TOKEN=...
  - GitHub secret (for automation): Settings → Secrets → LINKEDIN_ACCESS_TOKEN

PREREQUISITES:
  Your LinkedIn App redirect URI must include: http://localhost:8080/callback
  Go to: https://developers.facebook.com/apps → your app → OAuth 2.0 settings
  Actually: https://www.linkedin.com/developers/apps → your app → Auth tab → Redirect URLs
"""

import sys
import webbrowser
import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import requests

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# ─── Config ───────────────────────────────────────────────────────────────────
REDIRECT_URI = "http://localhost:8080/callback"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

# Scopes needed:
#   w_member_social        → post carousels on personal profile
#   rw_organization_social → post carousels on company/org page
#   openid + profile       → get your Person URN via /v2/userinfo
SCOPES = "openid profile w_member_social rw_organization_social"

# ─── Capture server ───────────────────────────────────────────────────────────
_auth_code = None


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _auth_code = params["code"][0]
            body = b"<h2>Authorization successful!</h2><p>You can close this tab.</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        else:
            error = params.get("error_description", ["Unknown error"])[0]
            body = f"<h2>Authorization failed</h2><p>{error}</p>".encode()
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # silence request logs


def _start_server():
    server = HTTPServer(("localhost", 8080), _CallbackHandler)
    server.handle_request()  # Handle exactly one request then stop


# ─── Main flow ────────────────────────────────────────────────────────────────

def main():
    print("\nLinkedIn OAuth Token Generator")
    print("=" * 45)
    print()

    client_id = input("Enter your LinkedIn App Client ID: ").strip()
    client_secret = input("Enter your LinkedIn App Client Secret: ").strip()

    if not client_id or not client_secret:
        print("❌ Client ID and Secret are required.")
        sys.exit(1)

    # Build auth URL
    auth_url = (
        f"https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
        f"&scope={urllib.parse.quote(SCOPES)}"
    )

    print("\n✅ Starting local callback server on port 8080...")
    print("   Make sure your LinkedIn App has this Redirect URI configured:")
    print(f"   {REDIRECT_URI}")
    print()

    # Start server in background thread
    t = threading.Thread(target=_start_server, daemon=True)
    t.start()

    print(f"🌐 Opening browser for authorization...")
    print(f"   (If it doesn't open automatically, visit:\n   {auth_url})")
    webbrowser.open(auth_url)

    # Wait for the callback
    t.join(timeout=120)

    if not _auth_code:
        print("\n❌ Timed out waiting for authorization. Did you approve the app?")
        sys.exit(1)

    print("\n✅ Authorization code received. Exchanging for access token...")

    # Exchange code for token
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": _auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=30)

    if resp.status_code != 200:
        print(f"❌ Token exchange failed: {resp.status_code} {resp.text}")
        sys.exit(1)

    token_data = resp.json()
    access_token = token_data["access_token"]
    expires_in_days = token_data.get("expires_in", 0) // 86400

    # Fetch Person URN
    userinfo_resp = requests.get(USERINFO_URL, headers={
        "Authorization": f"Bearer {access_token}"
    }, timeout=15)

    person_urn = None
    if userinfo_resp.ok:
        person_urn = userinfo_resp.json().get("sub", "")
        if person_urn and not person_urn.startswith("urn:li:person:"):
            person_urn = f"urn:li:person:{person_urn}"

    # ─── Output ───────────────────────────────────────────────────────────────
    print()
    print("=" * 55)
    print("✅  SUCCESS — copy these values:")
    print("=" * 55)
    print(f"\nLINKEDIN_ACCESS_TOKEN={access_token}")
    if person_urn:
        print(f"LINKEDIN_PERSON_URN={person_urn}")
    print(f"\n(Token expires in ~{expires_in_days} days)")
    print()
    print("─── Local .env file ────────────────────────────────────")
    print("Update these two lines in your .env file.")
    print()
    print("─── GitHub Actions secret ───────────────────────────────")
    print("Go to: GitHub repo → Settings → Secrets and variables →")
    print("       Actions → Update LINKEDIN_ACCESS_TOKEN")
    if person_urn:
        print("       Update LINKEDIN_PERSON_URN if it changed")
    print()


if __name__ == "__main__":
    main()
