"""Re-mint the NinniTales refresh token with FULL manage + analytics access.

Same loopback OAuth flow as assured-referral-autoposter/get_youtube_token.py. The
scope set is youtube.force-ssl (upload + schedule + delete — delete is what lets the
Telegram ❌ veto cancel a scheduled Short) plus yt-analytics.readonly (search-vs-feed
stats for analyze.py). This single token covers everything, so it's the last re-auth
you'll need. Run it once, then replace YOUTUBE_REFRESH_TOKEN_NINNITALES in your .env
AND the GitHub repo secret with the new value it prints.

Prereqs (already true for you): OAuth consent screen = "In production"; the OAuth
client lists http://localhost:3000/oauth2callback as a redirect URI.

Usage:
  cd ninnitales-shorts
  python get_youtube_token.py --expect-channel UCmeOOKiWH1vfdsS9XeKXJvQ
  # at the Google screen, SELECT THE NINNITALES CHANNEL.
"""

import argparse
import os
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

REDIRECT_URI = "http://localhost:3000/oauth2callback"
REDIRECT_HOST, REDIRECT_PORT = "localhost", 3000
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
# force-ssl = full manage (upload + schedule + DELETE, needed for Telegram veto;
# supersets youtube.upload and youtube.readonly). yt-analytics.readonly = stats.
# This one token does everything — no further re-auth needed.
SCOPES = (
    "https://www.googleapis.com/auth/youtube.force-ssl "
    "https://www.googleapis.com/auth/yt-analytics.readonly"
)

_captured: dict = {}


def _load_env() -> None:
    """Load this folder's .env then AssuredReferral's, so client id/secret resolve."""
    here = Path(__file__).parent
    for path in [here / ".env", here.parent / "assured-referral-autoposter" / ".env"]:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _captured["code"] = params.get("code", [None])[0]
        _captured["error"] = params.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        msg = ("Authorization received. Close this tab and return to the terminal."
               if not _captured.get("error")
               else f"Authorization failed: {_captured['error']}")
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode())

    def log_message(self, *args):  # silence
        pass


def _capture_code(auth_url: str) -> str:
    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _Handler)
    t = threading.Thread(target=server.handle_request)
    t.start()
    print("\nOpening your browser for Google authorization...")
    print("IMPORTANT: at the channel chooser, SELECT THE NINNITALES CHANNEL.")
    print(f"If it doesn't open, paste this URL:\n{auth_url}\n")
    webbrowser.open(auth_url)
    t.join(timeout=300)
    server.server_close()
    if _captured.get("error"):
        sys.exit(f"OAuth error: {_captured['error']}")
    if not _captured.get("code"):
        sys.exit("Timed out waiting for authorization (no code captured).")
    return _captured["code"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default="NINNITALES",
                    help="Suffix to read client_id/secret from (NINNITALES|ASSUREDREFERRAL).")
    ap.add_argument("--expect-channel", default=None,
                    help="Channel ID the token should control (safety check).")
    args = ap.parse_args()
    _load_env()

    client_id = (os.environ.get(f"YOUTUBE_CLIENT_ID_{args.src}")
                 or os.environ.get("YOUTUBE_CLIENT_ID_ASSUREDREFERRAL")
                 or os.environ.get("YOUTUBE_CLIENT_ID"))
    client_secret = (os.environ.get(f"YOUTUBE_CLIENT_SECRET_{args.src}")
                     or os.environ.get("YOUTUBE_CLIENT_SECRET_ASSUREDREFERRAL")
                     or os.environ.get("YOUTUBE_CLIENT_SECRET"))
    if not client_id or not client_secret:
        sys.exit("Missing YOUTUBE_CLIENT_ID/_SECRET in .env (NINNITALES or ASSUREDREFERRAL).")

    auth_url = f"{AUTH_URL}?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",  # force a fresh refresh_token
    })
    code = _capture_code(auth_url)

    resp = requests.post(TOKEN_URL, data={
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code",
    }, timeout=30)
    resp.raise_for_status()
    tokens = resp.json()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        sys.exit("No refresh_token returned. Revoke prior access at "
                 "myaccount.google.com/permissions, then re-run.")

    ch = requests.get("https://www.googleapis.com/youtube/v3/channels",
                      params={"part": "snippet", "mine": "true"},
                      headers={"Authorization": f"Bearer {tokens['access_token']}"},
                      timeout=30)
    channel_id = channel_title = "(could not read)"
    if ch.ok and ch.json().get("items"):
        item = ch.json()["items"][0]
        channel_id, channel_title = item["id"], item["snippet"]["title"]

    print("\n" + "=" * 60)
    print(f"TOKEN MINTED — channel: {channel_title} ({channel_id})")
    print("=" * 60)
    if args.expect_channel and channel_id != args.expect_channel:
        print(f"❌ MISMATCH! Expected {args.expect_channel}. You picked the wrong "
              "channel — re-run and DO NOT save this token.")
        return
    if args.expect_channel:
        print("✅ Matches expected channel.")
    print("\nUpdate this in your .env AND the GitHub repo secret:\n")
    print(f"YOUTUBE_REFRESH_TOKEN_NINNITALES={refresh_token}")


if __name__ == "__main__":
    main()
