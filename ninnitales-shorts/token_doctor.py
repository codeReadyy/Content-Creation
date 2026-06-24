"""token_doctor.py — find out WHY the NinniTales refresh token keeps dying.

The app is in production, so the 7-day "Testing" expiry isn't the cause. This tool
inspects the *actual* token and prints the truth instead of us guessing. Run it now
(while things work) to baseline, and again the moment it "expires" to capture the
real failure — the difference tells us exactly what's happening.

It reports:
  • WHICH env var supplied the token  — _NINNITALES, or did it silently fall back to
    the AssuredReferral YOUTUBE_REFRESH_TOKEN? (a fallback = wrong channel = looks
    "expired" but isn't)
  • is the refresh token ALIVE         — mints an access token, or the exact Google
    error (invalid_grant = revoked/expired vs anything else)
  • which SCOPES it actually carries   — confirms yt-analytics.readonly is present
  • which CHANNEL it controls          — must be the NinniTales channel
  • does an Analytics call SUCCEED     — the search-views thesis, live

Usage:
  cd ninnitales-shorts
  python token_doctor.py
  python token_doctor.py --expect-channel UCmeOOKiWH1vfdsS9XeKXJvQ
"""

import argparse
import os

import requests

import run_pipeline  # for _load_env()

TOKEN_URL = "https://oauth2.googleapis.com/token"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


def _token_source() -> tuple[str | None, str]:
    """Return (refresh_token, which-env-var-it-came-from) so a silent fallback to
    the AssuredReferral token (a different channel) is visible, not invisible."""
    suffixed = os.environ.get("YOUTUBE_REFRESH_TOKEN_NINNITALES")
    if suffixed:
        return suffixed, "YOUTUBE_REFRESH_TOKEN_NINNITALES"
    plain = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    if plain:
        return plain, "YOUTUBE_REFRESH_TOKEN (⚠️ fallback — may be the wrong channel!)"
    return None, "(none set)"


def check(expect_channel: str | None = None) -> dict:
    """Diagnose the current token. Returns a dict; never raises on auth failure."""
    run_pipeline._load_env()
    out: dict = {"alive": False, "source": None, "scopes": [], "analytics_ok": False,
                 "channel_id": None, "channel_title": None, "error": None}

    refresh, source = _token_source()
    out["source"] = source
    if not refresh:
        out["error"] = "no refresh token in env"
        return out

    client_id = (os.environ.get("YOUTUBE_CLIENT_ID_NINNITALES")
                 or os.environ.get("YOUTUBE_CLIENT_ID"))
    client_secret = (os.environ.get("YOUTUBE_CLIENT_SECRET_NINNITALES")
                     or os.environ.get("YOUTUBE_CLIENT_SECRET"))

    # 1) Is the refresh token alive? Capture Google's exact verdict.
    r = requests.post(TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh, "grant_type": "refresh_token",
    }, timeout=30)
    if not r.ok:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        out["error"] = f"{body.get('error', r.status_code)}: {body.get('error_description', r.text[:160])}"
        return out
    access = r.json()["access_token"]
    out["alive"] = True

    # 2) What scopes does this token actually carry?
    ti = requests.get(TOKENINFO_URL, params={"access_token": access}, timeout=30)
    if ti.ok:
        out["scopes"] = ti.json().get("scope", "").split()

    # 3) Which channel does it control?
    ch = requests.get(CHANNELS_URL, params={"part": "snippet", "mine": "true"},
                      headers={"Authorization": f"Bearer {access}"}, timeout=30)
    if ch.ok and ch.json().get("items"):
        item = ch.json()["items"][0]
        out["channel_id"], out["channel_title"] = item["id"], item["snippet"]["title"]

    # 4) Does an Analytics call actually succeed (the whole search-views thesis)?
    a = requests.get(ANALYTICS_URL, params={
        "ids": "channel==MINE", "startDate": "2020-01-01",
        "endDate": "2030-01-01", "metrics": "views",
    }, headers={"Authorization": f"Bearer {access}"}, timeout=30)
    out["analytics_ok"] = a.ok
    if not a.ok:
        out["analytics_error"] = a.text[:160]

    if expect_channel and out["channel_id"] and out["channel_id"] != expect_channel:
        out["error"] = (f"WRONG CHANNEL: token controls {out['channel_id']}, "
                        f"expected {expect_channel}")
    return out


def _report(d: dict) -> None:
    print("\n" + "=" * 60)
    print("NINNITALES TOKEN DOCTOR")
    print("=" * 60)
    print(f"token source   : {d['source']}")
    if not d["alive"]:
        print(f"refresh token  : ❌ DEAD — {d['error']}")
        if d.get("error", "").startswith("invalid_grant"):
            print("\n  → invalid_grant means the token was REVOKED or EXPIRED, not a "
                  "config bug. Likely: another mint pushed it past the per-user token "
                  "limit, an account security event, or the secret was overwritten. "
                  "Re-mint with get_youtube_token.py and update BOTH .env and the GitHub "
                  "secret.")
        return
    print("refresh token  : ✅ alive (minted an access token)")
    has_analytics = ANALYTICS_SCOPE in d["scopes"]
    print(f"analytics scope: {'✅ present' if has_analytics else '❌ MISSING — re-mint'}")
    print(f"analytics call : {'✅ works' if d['analytics_ok'] else '❌ ' + d.get('analytics_error', 'failed')}")
    print(f"channel        : {d['channel_title']} ({d['channel_id']})")
    if d.get("error"):
        print(f"⚠️  {d['error']}")
    print("\nScopes granted:")
    for s in d["scopes"]:
        print(f"  - {s}")
    print("\nVerdict: token is healthy." if d["alive"] and has_analytics and not d.get("error")
          else "\nVerdict: see warnings above.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnose the NinniTales YouTube token.")
    ap.add_argument("--expect-channel", default=None,
                    help="Channel ID the token must control (flags a fallback/wrong token).")
    args = ap.parse_args()
    _report(check(args.expect_channel))


if __name__ == "__main__":
    main()
