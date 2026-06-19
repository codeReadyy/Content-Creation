"""
One-time YouTube refresh-token minter.

Reuses an EXISTING Google Cloud project's OAuth client (same client_id/secret as
another product) and authorizes whichever channel you pick at the consent screen.
Verifies which channel the resulting token controls so you don't mint a token for
the wrong channel by accident.

Prereqs:
  - OAuth consent screen publishing status = "In production" (so the refresh
    token does NOT expire after 7 days).
  - The OAuth client lists  http://localhost:8080  as an authorized redirect URI
    (Desktop-app clients allow loopback by default).

Usage:
  cd assured-referral-autoposter
  # source the client_id/secret of the project you're reusing, e.g. AssuredReferral:
  python get_youtube_token.py --from ASSUREDREFERRAL --expect-channel UCmeOOKiWH1vfdsS9XeKXJvQ

  Then, at the Google screen, SELECT THE NINNITALES CHANNEL.
"""

import argparse
import os
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

REDIRECT_URI = "http://localhost:3000/oauth2callback"
REDIRECT_HOST = "localhost"
REDIRECT_PORT = 3000
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
# upload = the scope we actually need; readonly = lets us confirm the channel id.
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload "
    "https://www.googleapis.com/auth/youtube.readonly"
)

_captured = {}


def _load_env_file(path: str = ".env") -> None:
    """Minimal .env loader (avoids hard dependency on python-dotenv)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        _captured["code"] = params.get("code", [None])[0]
        _captured["error"] = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = "Authorization received. You can close this tab and return to the terminal."
        if _captured.get("error"):
            msg = f"Authorization failed: {_captured['error']}"
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode())

    def log_message(self, *args):  # silence server logs
        pass


def _capture_code(auth_url: str) -> str:
    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _Handler)
    t = threading.Thread(target=server.handle_request)  # serve exactly one request
    t.start()
    print("\nOpening your browser for Google authorization...")
    print("IMPORTANT: at the account/channel chooser, SELECT THE TARGET CHANNEL.")
    print(f"If the browser doesn't open, paste this URL manually:\n{auth_url}\n")
    webbrowser.open(auth_url)
    t.join(timeout=300)
    server.server_close()
    if _captured.get("error"):
        sys.exit(f"OAuth error: {_captured['error']}")
    code = _captured.get("code")
    if not code:
        sys.exit("Timed out waiting for authorization (no code captured).")
    return code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default="ASSUREDREFERRAL",
                    help="Product suffix to read client_id/secret from (e.g. ASSUREDREFERRAL).")
    ap.add_argument("--expect-channel", default=None,
                    help="Channel ID you expect the token to control (verification).")
    args = ap.parse_args()

    _load_env_file()

    client_id = (os.environ.get(f"YOUTUBE_CLIENT_ID_{args.src}")
                 or os.environ.get("YOUTUBE_CLIENT_ID"))
    client_secret = (os.environ.get(f"YOUTUBE_CLIENT_SECRET_{args.src}")
                     or os.environ.get("YOUTUBE_CLIENT_SECRET"))

    if not client_id or not client_secret:
        sys.exit(f"Missing YOUTUBE_CLIENT_ID_{args.src} / _SECRET_{args.src} in .env")

    print(f"Reusing OAuth client from project: {args.src}")
    print(f"  client_id: {client_id[:24]}...")

    auth_url = (
        f"{AUTH_URL}?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",  # force a refresh_token every time
        })
    )

    code = _capture_code(auth_url)

    # Exchange code -> tokens
    resp = requests.post(TOKEN_URL, data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }, timeout=30)
    resp.raise_for_status()
    tokens = resp.json()

    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")
    if not refresh_token:
        sys.exit("No refresh_token returned. Re-run (prompt=consent forces one); "
                 "if it persists, revoke prior access at myaccount.google.com/permissions.")

    # Verify which channel this token controls
    ch_resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "snippet", "mine": "true"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    channel_id = channel_title = "(could not read)"
    if ch_resp.ok and ch_resp.json().get("items"):
        item = ch_resp.json()["items"][0]
        channel_id = item["id"]
        channel_title = item["snippet"]["title"]

    print("\n" + "=" * 60)
    print("TOKEN MINTED")
    print("=" * 60)
    print(f"Channel authorized: {channel_title}")
    print(f"Channel ID:         {channel_id}")

    if args.expect_channel:
        if channel_id == args.expect_channel:
            print("✅ MATCHES expected channel.")
        else:
            print(f"❌ MISMATCH! Expected {args.expect_channel}.")
            print("   You picked the wrong channel at the consent screen. Re-run and")
            print("   select the correct one. Do NOT save this token.")
            return

    print("\nAdd these to your .env (note: client id/secret are the SAME as the")
    print("source project — only the refresh token + channel id are new):\n")
    print(f"YOUTUBE_CLIENT_ID_NINNITALES={client_id}")
    print(f"YOUTUBE_CLIENT_SECRET_NINNITALES={client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN_NINNITALES={refresh_token}")
    print(f"YOUTUBE_CHANNEL_ID_NINNITALES={channel_id}")
    print("\n(For GitHub Actions, add the same four as repository secrets.)")


if __name__ == "__main__":
    main()
